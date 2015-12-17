from git import Repo
import subprocess
import os

from oslo_log import log
from oslo_config import cfg
from git import exc

from nova.openstack.common import fileutils
from nova.image import glance
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt import images


environ = os.environ.copy()

unikernel_opts = [
    cfg.StrOpt('branch',
               default='master',
               help='branch'),
    cfg.StrOpt('repo_base',
               default='/opt/stack/data/unikernel',
               help='unikernels repo path'),
]

CONF = cfg.CONF
CONF.register_opts(unikernel_opts, 'unikernel')

LOG = log.getLogger(__name__)


class UnikernelDriver(libvirt_driver.LibvirtDriver):

    def __init__(self, virtapi):
        super(UnikernelDriver, self).__init__(virtapi)

    def _try_fetch_image_cache(self, image, fetch_func, context, filename,
                               image_id, instance, size,
                               fallback_from_host=None):


        repository_url = self.get_repository_url(context, instance.image_ref)

        # Fetch the image
        try:
            LOG.info("Trying to fetch repository...")
            if self.image_pulling(instance, filename, repository_url, image_id,
                                  CONF.unikernel.repo_base,
                                  CONF.unikernel.branch):
                LOG.info("Repository updated, compiling image...")
                self.compile_image(CONF.unikernel.repo_base, image_id)
            else:
                LOG.info("Repository already updated")
        except:
            LOG.info("Could not pull the image")


 #      image.cache(fetch_func=fetch_func,
 #                  context=context,
 #                  filename=filename,
 #                  image_id=image_id,
 #                  user_id=instance.user_id,
 #                  project_id=instance.project_id,
 #                  size=size)

    def image_pulling(self, instance, filename, repo_url,image_id, repo_base, branch):

        unikernel_repo = self.get_unikernel_repo(repo_base, image_id)
        repo = Repo.init(unikernel_repo)

        try:
            origin = repo.create_remote('origin', repo_url)
        except:
            origin = repo.remotes['origin']

        try:
            origin.fetch(branch)
        except exc.GitCommandError:
            raise

        if self.check_branch_diffs(repo, branch):
            origin.pull(origin.refs[branch].remote_head)
            return True
        else:
            return False

    def convert_image_to_raw(compiled_image_path, target_path):
        if os.path.exists(compiled_image_path):
            os.unlink(target_path)
            images.convert_image(compiled_image_path, target_path, 'raw')

    def get_repository_url(self, context, image_ref):
        image_service = glance.get_default_image_service()
        image_top = image_service.show(context, image_ref)
        return image_top.get('name')

    def check_branch_diffs(self, repo, branch):
        return repo.git.diff("origin/%s" % branch)

    def check_image(self):
        pass

    def get_unikernel_repo(self, repo_base, image_id):
        return os.path.join(repo_base, image_id)

    def get_image_cache_dir(self, filename):
        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)

        return os.path.join(base_dir, filename)

    def compile_image(self, repo_base,  image_id):
        unikernel_repo = self.get_unikernel_repo(repo_base, image_id)
        build_image_path = os.path.join(unikernel_repo,
                                           image_id + '.qemu')
        LOG.debug("Recompiling image ...")
        p = subprocess.Popen(['capstan', 'build', image_id],
                             cwd=unikernel_repo,
                             env=dict(environ, CAPSTAN_ROOT=repo_base))
        p.wait()

        return build_image_path
