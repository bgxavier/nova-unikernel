from git import Repo
import subprocess
import os

from oslo_log import log
from oslo_config import cfg
from git import exc

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

        # Get the image name ( it represents the remote repository )
        image_service = glance.get_default_image_service()
        image_top = image_service.show(context,
                                       instance.image_ref)
        repo_url = image_top.get('name')

        # Fetch the image
        self.image_fetch(instance,
                         filename,
                         repo_url,
                         image_id,
                         CONF.unikernel.repo_base,
                         CONF.unikernel.branch)

        image.cache(fetch_func=fetch_func,
                    context=context,
                    filename=filename,
                    image_id=image_id,
                    user_id=instance.user_id,
                    project_id=instance.project_id,
                    size=size)

    def image_fetch(self, instance, filename, repo_url, image_id, repo_base,
                    branch):

        # initialize the unikernel repository
        unikernel_repo = os.path.join(repo_base, image_id)
        repo = Repo.init(unikernel_repo)

        LOG.debug("Fetching repo %s...", repo_url)

        try:
            origin = repo.create_remote('origin', repo_url)
        except:
            origin = repo.remotes['origin']

        try:
            origin.fetch(branch)
        except exc.GitCommandError:
            raise

        origin.pull(origin.refs[branch].remote_head)

        self.compile_image(repo_base, unikernel_repo, image_id)

        # Convert from qcow2 to raw
        instance_path = os.path.join(CONF.instances_path, '_base')
        LOG.debug("Converting image %s", instance_path)
        staged_path = os.path.join(instance_path, filename)

        if os.path.exists(staged_path):
            os.unlink(staged_path)

        compiled_image = os.path.join(unikernel_repo,
                                      image_id + '.qemu')
        images.convert_image(compiled_image, staged_path, 'raw')

    def check_branch_diffs(self, repo, branch):
        return repo.git.diff("origin/%s" % branch)

    def compile_image(self, repo_base, unikernel_repo,  image_id):
        LOG.debug("Recompiling image ...")
        p = subprocess.Popen(['capstan', 'build', image_id],
                             cwd=unikernel_repo,
                             env=dict(environ, CAPSTAN_ROOT=repo_base))
        p.wait()
