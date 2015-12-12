from git import Repo
import subprocess
import os
import shutil

from oslo_log import log
from oslo_config import cfg
from oslo_utils import units

from nova import utils
from nova import image
from nova.compute import utils as compute_utils
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import driver
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt import images

environ = os.environ.copy()
repo_path = '/opt/stack/data/unikernel'
path_tmp = '/tmp/glance/unikernel/unikernel.qemu'
staged = '/tmp/glance/unikernel/unikernel.converted'

libvirt_opts = []

CONF = cfg.CONF
CONF.register_opts(libvirt_opts, 'libvirt')

LOG = log.getLogger(__name__)

class UnikernelDriver(driver.LibvirtDriver):

  #  def _create_image(self):
   #     self.fetch_from_source(image_meta)
    #    self.compile(repo_path,image_meta)

    def __init__(self, virtapi):
        super(UnikernelDriver, self).__init__(virtapi)
        self.image_api = image.API()

    def _create_image(self, context, instance,
                      disk_mapping, suffix='',
                      disk_images=None, network_info=None,
                      block_device_info=None, files=None,
                      admin_pass=None, inject_files=True,
                      fallback_from_host=None):

        def image(fname, image_type=CONF.libvirt.images_type):
            return self.image_backend.image(instance,
                                            fname + suffix, image_type)        

        if not disk_images:
            disk_images = {'image_id': instance.image_ref,
                           'kernel_id': instance.kernel_id,
                           'ramdisk_id': instance.ramdisk_id}

        inst_type = instance.get_flavor() # flavor
        root_fname = imagecache.get_cache_fname(disk_images, 'image_id') # filename in _base
        size = instance.root_gb * units.Gi # size of the image
        backend = image('disk')

        image_ref = instance.get('image_ref') 
        image_meta = compute_utils.get_image_metadata(
            context, self.image_api, image_ref, instance)

        # Fetch from git
        self.fetch_from_source(image_meta)

        # Compile the image
        self.compile(repo_path,image_meta)
        
        # Retrieve the format and virtual size
        data = images.qemu_img_info(path_tmp)

        disk_size = data.virtual_size
        fmt = data.file_format

        # Convert from qcow2 to raw
        images.convert_image(path_tmp, staged, 'raw')

        # Remove the old qcow image
        os.unlink(path_tmp)

        # Rename the converted image
        os.rename(staged, path)

        LOG.debug("TESTANDO %s", )

    def _try_fetch_image_cache(self, image, fetch_func, context, filename,
                               image_id, instance, size,
                               fallback_from_host=None):
        try:
            image.cache(fetch_func=fetch_func,
                        context=context,
                        filename=filename,
                        image_id=image_id,
                        user_id=instance.user_id,
                        project_id=instance.project_id,
                        size=size)
        except exception.ImageNotFound:
            if not fallback_from_host:
                raise
            LOG.debug("Image %(image_id)s doesn't exist anymore "
                      "on image service, attempting to copy "
                      "image from %(host)s",
                      {'image_id': image_id, 'host': fallback_from_host})

            def copy_from_host(target, max_size):
                libvirt_utils.copy_image(src=target,
                                         dest=target,
                                         host=fallback_from_host,
                                         receive=True)
            image.cache(fetch_func=copy_from_host,
                        filename=filename)

    def compile(self, path, image_meta):
       p = subprocess.Popen(['capstan', 'build'], cwd=path,env=dict(environ, CAPSTAN_ROOT='/tmp/glance'))
       p.wait()

    def fetch_from_source(self,image_meta):
        LOG.debug("Fetching repo %s...", image_meta['name'])
        repo = Repo.init(repo_path)
        try:
            origin = repo.create_remote('origin',image_meta['name'])
        except:
            origin = repo.remotes['origin']
        origin.fetch()
        origin.pull(origin.refs[0].remote_head)
        LOG.debug("Repositorio atualizado %s...", image_meta['name'])
        



