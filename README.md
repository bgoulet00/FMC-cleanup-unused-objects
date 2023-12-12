# FMC-cleanup-unused-objects
delete unused network, range, host and group objects from cisco FMC

this script will identify unused network objects of type Network, Range, Host and Group.
FMC will not allow deletion of objects in use, additionally, this script is only acting on objects marked not in use.
As an additional level of safety, the objects being deleted will be backed up in csv files prior to deletion.
An accompanying script in this project will restore the objects from those backup files if needed. 
It is still recommended that a valid FMC system backup be performed prior to cleanup


BASE_URL needs to be updated with the FMC url/ip

Developed and tested with the following environment
- OS: linux
- Python: 3.6.8
- Target platform:  FMC 7.0.4
- Dependencies: none
- Comments: there is a lot of repeat code in main() that probably could have been functionalized
