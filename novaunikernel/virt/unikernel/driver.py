from nova.virt.libvirt import driver

class UnikernelDriver(driver.LibvirtDriver):

    def spawn(self):
        
        Repo.clone_from("git@localhost:/opt/git/charuto.git","/opt/stack/data/unikernel")