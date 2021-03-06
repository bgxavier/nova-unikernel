from git import Repo
import os

from oslo_log import log
from oslo_config import cfg
from git import exc
from cgroups import Cgroup

from nova.openstack.common import fileutils
from nova.image import glance
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt import images
from nova import utils

import getpass

environ = os.environ.copy()

CONF = cfg.CONF

unikernel_opts = [
    cfg.StrOpt('branch',
               default='master',
               help='branch'),
    cfg.StrOpt('compile_core_limit',
               default=50,
               help='Number of cores used for compiling'),
    cfg.StrOpt('compile_mem_limit',
               default=20,
               help='Memory used for compiling'),
    cfg.StrOpt('repo_base',
               default='/opt/stack/data/unikernel',
               help='unikernels repo path'),
]

CONF.register_opts(unikernel_opts, 'unikernel')

LOG = log.getLogger(__name__)


class UnikernelDriver(libvirt_driver.LibvirtDriver):

    def __init__(self, virtapi):
        super(UnikernelDriver, self).__init__(virtapi)
        self.lock_path = os.path.join(CONF.instances_path, 'locks')
        self.cg = self.setup_cgroups(CONF.unikernel.compile_core_limit,
                                     CONF.unikernel.compile_mem_limit)

    def _try_fetch_image_cache(self, image, fetch_func, context, filename,
                               image_id, instance, size,
                               fallback_from_host=None):

        repository_url = self.get_repository_url(context, instance.image_ref)

        # Pega o diretorio completo do cache da imagem no _base
        image_cache_dir = self.get_image_cache_dir(filename)

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def do_fetch(instance, repository_url, image_id, image_cache_dir):
            do_compile = None
            try:
                # Verifica se houve mudancas no repositorio
                if not self.image_pulling(instance, repository_url,
                                          image_id,
                                          CONF.unikernel.repo_base,
                                          CONF.unikernel.branch):
                    LOG.info("Repository already updated")
                    # Se nao existe mudancas, verifica se
                    # ja existe o cache da imagem.
                    # Caso nao exista, recompila
                    if not self.check_image_exists(image_cache_dir):
                        do_compile = True
                else:
                    # Se existe mudancas, recompila sempre
                    LOG.info("Repository fetched, compiling image...")
                    do_compile = True
            except:
                LOG.info("Could not pull the image")

            if do_compile:
                # Compila o unikernel e retorna o caminho da imagem compilada
                image_build_path = self.compile_image(CONF.unikernel.repo_base,
                                                      image_id,
                                                      filename)
                # Converte a imagem compilada para RAW no cache de imagens
                self.convert_image_to_raw(image_build_path, image_cache_dir)

        do_fetch(instance, repository_url, image_id, image_cache_dir)

        image.cache(fetch_func=fetch_func,
                    context=context,
                    filename=filename,
                    image_id=image_id,
                    user_id=instance.user_id,
                    project_id=instance.project_id,
                    size=size)

    def image_pulling(self, instance, repository_url, image_id,
                      repo_base,
                      branch):

        LOG.info("Trying to fetch repository...")
        unikernel_repo = self.get_unikernel_repo(repo_base, image_id)

        if not os.path.exists(unikernel_repo):
            utils.execute('git', 'clone', repository_url, unikernel_repo)
        else:
            utils.execute('git', 'fetch', cwd=unikernel_repo)

        (out, error) = utils.execute('git', 'diff', 'origin/' + branch, cwd=unikernel_repo)
        if out:
            utils.execute('git', 'pull', cwd=unikernel_repo)
            return True
        else:
            return False

    def convert_image_to_raw(self, image_build_path, target_path):
        # Se a imagem ja existe, remove
        if os.path.exists(target_path):
            os.unlink(target_path)

        images.convert_image(image_build_path, target_path, 'qcow2', 'raw')
        os.unlink(image_build_path)

    def get_repository_url(self, context, image_ref):
        image_service = glance.get_default_image_service()
        image_top = image_service.show(context, image_ref)
        return image_top.get('name')

    def check_image_exists(self, image_cache_dir):
        return os.path.exists(image_cache_dir)

    def check_repo_exists(self, path):
        pass


    def get_unikernel_repo(self, repo_base, image_id):
        return os.path.join(repo_base, image_id)

    def get_image_cache_dir(self, filename):
        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)

        return os.path.join(base_dir, filename)

    def compile_image(self, repo_base, image_id, filename):
        LOG.info("Compiling image... %s %s", repo_base, filename)
        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)

        image_name = os.path.join(filename + ".build")
        unikernel_repo = self.get_unikernel_repo(repo_base, image_id)
        image_build_path = os.path.join(base_dir, image_name,
                                        image_name + '.qemu')

        def _add_pid_to_cgroup():
            pid = os.getpid()
            self.cg.add(pid)

        utils.execute('capstan', 'build', image_name,
                      preexec_fn=_add_pid_to_cgroup,
                      env_variables=dict(environ, CAPSTAN_ROOT=base_dir),
                      cwd=unikernel_repo)

        return image_build_path

    def setup_cgroups(self, core_limit, mem_limit):
        process_user = getpass.getuser()
        try:
            utils.execute('user_cgroups', process_user, run_as_root=True)
            cg = Cgroup('capstan')
            cg.set_cpu_limit(core_limit)
            cg.set_memory_limit(mem_limit)
            return cg
        except:
            LOG.info("Verify whether the cgroups library was properly installed")
            raise
