# FMC-cleanup-unused-objects
delete unused network, range, host and group objects from cisco FMC

this script will identify unused network objects of type Network, Range, Host and Group
FMC will not allow deletion of objects in use, additionally, this script is only acting on objects marked not in use
as an additional level of safety, the objects being deleted will be backed up in csv files prior to deletion
an accompanying script in this project will restore the objects from those backup files if needed 
it is still recommended that a valid FMC system backup be performed prior to cleanup


BASE_URL needs to be updated with the FMC url/ip

Developed and tested with the following environment
- OS: linux
- Python: 3.6.8
- Target platform:  FMC 7.0.4
- Dependencies: none
- Limitations: system created objects cannot be deteted.  operation not permited warnings will display when the script encounters these objects
              in production run it was discovered groups might contain groups that containd groups, etc.  the child groups aren't marked unused
              until the parent group is removed so multiple runs are required until unused groups is 0
- Comments: there is a lot of repeat code in main() that probably could have been functionalized
