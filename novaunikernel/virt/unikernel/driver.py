from git import Repo
import subprocess
import os
import shutil

from oslo_log import log

from nova.virt.libvirt import driver

environ = os.environ.copy()
repo_path = '/opt/stack/data/unikernel'

LOG = log.getLogger(__name__)

class UnikernelDriver(driver.LibvirtDriver):

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):

        self.fetch_from_source(image_meta)
        self.compile(repo_path,image_meta)

        super(self.__class__,self).spawn(context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info)

    def compile(self, path, image_meta):
       p = subprocess.Popen(['capstan', 'build'], cwd=path,env=dict(environ, CAPSTAN_ROOT='/tmp/glance'))
       p.wait()    
       shutil.copy('/tmp/glance/unikernel/unikernel.qemu', '/opt/stack/data/glance/images/' + image_meta['id'])

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
        



