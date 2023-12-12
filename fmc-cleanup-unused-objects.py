# this script will identify unused network objects of type Network, Range, Host and Group
# FMC will not allow deletion of objects in use, additionally, this script is only acting on objects marked not in use
# as an additional level of safety, the objects being deleted will be backed up in csv files prior to deletion
# an accompanying script in this project will restore the objects from those backup files if needed 
# it is still recommended that a valid FMC system backup be performed prior to cleanup


# BASE_URL needs to be updated with the FMC url/ip

# Developed and tested with the following environment
# - OS: linux
# - Python: 3.6.8
# - Target platform:  FMC 7.0.4
# - Dependencies: none
# - Limitations: system created objects cannot be deteted.  operation not permited warnings will display when the script encounters these objects
#               in production run it was discovered groups might contain groups that containd groups, etc.  the child groups aren't marked unused
#               until the parent group is removed so multiple runs are required until unused groups is 0
# - Comments: there is a lot of repeat code in main() that probably could have been functionalized


import requests
from requests.auth import HTTPBasicAuth
import json
import csv
import os
import sys
import time
from datetime import date

# Disable SSL warnings
import urllib3
urllib3.disable_warnings()

# Global Variables
BASE_URL = 'https://192.168.100.22'
logFile = 'fmc-cleanup-unused-objects.log'


# prompt user for FMC credentials
# login to FMC and return the value of auth tokens and domain UUID from the response headers
# exit with an error message if a valid response is not received
def login():
    print('\n\nEnter FMC Credentials')
    user = input("USERNAME: ").strip()
    passwd = input("PASSWORD: ").strip()
    response = requests.post(
       BASE_URL + '/api/fmc_platform/v1/auth/generatetoken',
       auth=HTTPBasicAuth(username=user, password=passwd),
       headers={'content-type': 'application/json'},
       verify=False,
    )
    if response:
        return {'X-auth-access-token': response.headers['X-auth-access-token'], 
        'X-auth-refresh-token':response.headers['X-auth-refresh-token'],
        'DOMAIN_UUID':response.headers['DOMAIN_UUID']}
    else:
        sys.exit('Unable to connect to ' + BASE_URL + ' using supplied credentials')

# given the auth token and domain ID get all network objects of the provided object type
# return the json data from the get
# FMC limits the number of responses to a query so mulitiple queries are required
# each subsequent query will have the offset incremented by the limit
def netObjectsList(token, DUUID, objType):

    #list to contain network objects dictionaries
    objects = []
    #query paramaters to control results limit and offset. 1000 is max limit
    limit = str(1000)
    offset = str(0)
    querystring = {'offset':offset,'limit':limit}
    
    #perform the initial query to determine the number of pages of objects
    response = requests.get(
       BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
       headers={'X-auth-access-token':token},
       params=querystring,
       verify=False,
    )
    
    #get the json data and retrieve the value of the page count object
    raw = response.json()
    p = raw['paging']['pages']
    
    #query all pages of data
    for pages in range(p):
        response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
            headers={'X-auth-access-token':token},
            params=querystring,
            verify=False,
        )
        raw = response.json()
        for i in raw['items']:
            objects.append(i)
        offset += limit
        querystring = {'offset':offset,'limit':limit}
    
    return objects

# given the auth token and domain ID get all unused network objects of the provided object type
# return the json data from the get
# FMC limits the number of responses to a query so mulitiple queries are required
# each subsequent query will have the offset incremented by the limit
def unusednetObjectsList(token, DUUID, objType):

    #list to contain network objects dictionaries
    objects = []
    #query paramaters to control results limit and offset. 1000 is max limit
    limit = str(1000)
    offset = str(0)
    querystring = {'filter':'unusedOnly:true','offset':offset,'limit':limit, 'expanded':'true'}
    
    #perform the initial query to determine the number of pages of objects
    response = requests.get(
       BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
       headers={'X-auth-access-token':token},
       params=querystring,
       verify=False,
    )
    
    #get the json data and retrieve the value of the page count object
    raw = response.json()
    p = raw['paging']['pages']
    
    #query all pages of data and copy items to new list if they are not readonly system objects
    for pages in range(p):
        response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
            headers={'X-auth-access-token':token},
            params=querystring,
            verify=False,
        )
        raw = response.json()
        for i in raw['items']:
            if 'readOnly' in i['metadata']:
                if i['metadata']['readOnly']['state'] == True:
                    pass
            else:
                objects.append(i)
        offset += limit
        querystring = {'filter':'unusedOnly:true','offset':offset,'limit':limit, 'expanded':'true'}
    
    return objects
    

# taking a list of network objects and filename as input
# output the object list data to csv file
def outputObjects(objList, filename):
    outFile = filename
    # list to store data from input file
    dataInput = []
    # define csv columns
    dataOutput_columns = ["name", "id", "type", "links"]
    
    with open(outFile, "w") as file:
        writer = csv.DictWriter(file, fieldnames=dataOutput_columns)
        for item in objList:
            writer.writerow(item)

# backup function takes a list of objects and the object type as input
# it will perform a get for each object in the list to get that objects details
# the data gathered will be appended to a new objects[] list  
# the data from objects in that list will be output to a csv file
# FMC has a request limit of 120 reguest per minute so a sleep timer kicks in if the 429 code is returned
def netObjectsBackup(token, DUUID, objType, objList):

    #create a list for storing object dictionaries
    objects = []
    #create an ouput filename containing the backup object type and todays date
    today = str(date.today())
    outFile = 'FMC-' + objType + '-object-backup-' + today + '.csv'
    #define object dictionary keys to be used for output csv columns
    dataOutput_columns = ["name", "description", "type", "value"]
        
    for i in objList:
        response = requests.get(
        BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType + '/' + i['id'],
        headers={'X-auth-access-token':token},
        verify=False,
        )
        if response.status_code == 429:
            print('request limit reached. pausing 1 minute')
            time.sleep(61)
            response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType + '/' + i['id'],
            headers={'X-auth-access-token':token},
            verify=False,
            )
            
        raw = response.json()
        objects.append({'name':raw['name'], 'description':raw['description'], 'type':raw['type'], 'value':raw['value']})
        
    with open(outFile, "w") as file:
        writer = csv.DictWriter(file, fieldnames=dataOutput_columns)
        for item in objects:
            writer.writerow(item)
    
    
# create output backup file of group objects
# this output is for reference only and does not contain the data required to programtically restore the groups
def netGroupBackup(token, DUUID, objList, loop_count):

    #create lists for storing object dictionaries
    objects = []
    #create an ouput filename containing todays date
    today = str(date.today())
    outFile = 'FMC-network-group-object-backup-' + today + '.csv'
    #define object dictionary keys to be used for output csv columns
    dataOutput_columns = ["name", "description", "type", "objects", "literals", "pass"]
    
    #on first iteration open file as write.  in subsequent calls append the file
    if loop_count == 1:
        open_method = 'w'
    else:
        open_method = 'a'

    for i in objList:
        response = requests.get(
        BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/networkgroups/' + i['id'],
        headers={'X-auth-access-token':token},
        verify=False,
        )

        raw = response.json()
        obj_members = []
        lit_members = []
        if 'objects' in raw.keys():
            for object in raw['objects']:
                obj_members.append(object['name'])
        if 'literals' in raw.keys():
            for object in raw['literals']:
                lit_members.append({'type':object['type'], 'value':object['value']})
        objects.append({'name':raw['name'], 'description':raw['description'], 'type':raw['type'], 'objects':obj_members, 'literals':lit_members, 'pass':loop_count})
                
    with open(outFile, open_method) as file:
        writer = csv.DictWriter(file, fieldnames=dataOutput_columns)
        for item in objects:
            writer.writerow(item)

# delete a single object given the object type and object ID
# FMC has a request limit of 120 reguest per minute so a sleep timer kicks in if the 429 code is returned
def deleteObject(token, DUUID, objType, objID):

    response = requests.delete(
       BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType + '/' + objID,
       headers={'X-auth-access-token':token},
       verify=False,
    )
    
    if response.status_code == 429:
            print('request limit reached. pausing 1 minute')
            time.sleep(61)
            response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType + '/' + objID,
            headers={'X-auth-access-token':token},
            verify=False,
            )
            
    
    return response.json()

# output logging to log file and terminal        
def logging(out_str):
    print(out_str)
    with open(logFile, "a") as file:
        file.write(out_str + '\n')


def main():

    result = login()
    token = result.get('X-auth-access-token')
    DUUID = result.get('DOMAIN_UUID')
    separator = '\n---------------------------------------------------'

    print('\nThis program will identify, document and delete unused network objects from FMC')
    print('Note that factory default system created objects are not elligible for deletion and will be skipped')
    if (input("\nDo you want to continues? (y/n)") != 'y'):
        sys.exit()
    
    #create empty log file
    with open(logFile, "w") as file:
        pass
        
    #delete unused groups
    #child groups won't show as unused until partent group is deleted so this section will delete groups in loop
    #until there are no more unused group objects remaining
    logging(separator)
    logging('\nGathering network group oject information....')
    totalGroupsList = netObjectsList(token, DUUID, 'networkgroups')
    unusedGroupsList = unusednetObjectsList(token, DUUID, 'networkgroups')
    groups_before = len(totalGroupsList)
    print('At least ' + str(len(unusedGroupsList)) + ' out of ' + str(len(totalGroupsList)) + ' network group objects are unused')
    print('There may be more')
    if (input("Do you want to delete unused groups? (y/n)") == 'y'):
        loop_count = 1
        while len(unusedGroupsList) > 0:
            print('\nBacking up objects....')
            netGroupBackup(token, DUUID, unusedGroupsList, loop_count)
            print('Deleting objects, pass ' + str(loop_count) + '....')
            for item in unusedGroupsList:
                result = deleteObject(token, DUUID, 'networkgroups', item['id'])
                if 'error' in result.keys():
                    out_str = 'Unable to delete group ' + item['name'] + ' Error: ' + result['error']['messages'][0]['description']
                    logging(out_str)
            unusedGroupsList = unusednetObjectsList(token, DUUID, 'networkgroups')
            loop_count += 1
        print('\nGathering updated oject information....')
        totalGroupsList = netObjectsList(token, DUUID, 'networkgroups')
        unusedGroupsList = unusednetObjectsList(token, DUUID, 'networkgroups')
        groups_after = len(totalGroupsList)
        print(str(len(unusedGroupsList)) + ' out of ' + str(len(totalGroupsList)) + ' network group objects are unused')
    else:
        groups_after = groups_before
    if (input("\nDo you want to continues? (y/n)") != 'y'):
        sys.exit()
    
    #delete unused network objects
    logging(separator)
    logging('\nGathering network oject information....')
    totalNetsList = netObjectsList(token, DUUID, 'networks')
    unusedNetsList = unusednetObjectsList(token, DUUID, 'networks')
    networks_before = len(totalNetsList)
    print(str(len(unusedNetsList)) + ' out of ' + str(len(totalNetsList)) + ' network objects are unused')
    print('Note: There may be additional items that are members of unused groups.  Unused groups need to be removed before those members will be marked unused')
    print('\nBacking up objects....')
    netObjectsBackup(token, DUUID, 'networks', unusedNetsList)
    if (input("Do you want to delete unused network objects? (y/n)") == 'y'):
        print('Deleting objects....')
        for item in unusedNetsList:
            result = deleteObject(token, DUUID, 'networks', item['id'])
            if 'error' in result.keys():
                out_str = 'Unable to delete network object ' + item['name'] + ' Error: ' + result['error']['messages'][0]['description']
                logging(out_str)
        print('\nGathering updated oject information....')
        totalNetsList = netObjectsList(token, DUUID, 'networks')
        unusedNetsList = unusednetObjectsList(token, DUUID, 'networks')
        networks_after = len(totalNetsList)
        print(str(len(unusedNetsList)) + ' out of ' + str(len(totalNetsList)) + ' network objects are unused')
    else:
        networks_after = networks_before
    if (input("\nDo you want to continues? (y/n)") != 'y'):
        sys.exit()
    
    #delete unused range objects
    logging(separator)
    logging('\nGathering network range oject information....')
    totalRangesList = netObjectsList(token, DUUID, 'ranges')
    unusedRangesList = unusednetObjectsList(token, DUUID, 'ranges')
    ranges_before = len(totalRangesList)
    print(str(len(unusedRangesList)) + ' out of ' + str(len(totalRangesList)) + ' range objects are unused')
    print('Note: There may be additional items that are members of unused groups.  Unused groups need to be removed before those members will be marked unused')
    print('\nBacking up objects....')
    netObjectsBackup(token, DUUID, 'ranges', unusedRangesList)
    if (input("Do you want to delete unused range objects? (y/n)") == 'y'):
        print('Deleting objects....')
        for item in unusedRangesList:
            result = deleteObject(token, DUUID, 'ranges', item['id'])
            if 'error' in result.keys():
                out_str = 'Unable to delete range object ' + item['name'] + ' Error: ' + result['error']['messages'][0]['description']
                logging(out_str)
        print('\nGathering updated oject information....')
        totalRangesList = netObjectsList(token, DUUID, 'ranges')
        unusedRangesList = unusednetObjectsList(token, DUUID, 'ranges')
        ranges_after = len(totalRangesList)
        print(str(len(unusedRangesList)) + ' out of ' + str(len(totalRangesList)) + ' range objects are unused')
    else:
        ranges_after = ranges_before
    if (input("\nDo you want to continues? (y/n)") != 'y'):
        sys.exit()

    #delete unused host objects
    logging(separator)
    logging('\nGathering network host oject information....')
    totalHostsList = netObjectsList(token, DUUID, 'hosts')
    unusedHostsList = unusednetObjectsList(token, DUUID, 'hosts')
    hosts_before = len(unusedHostsList)
    print(str(len(unusedHostsList)) + ' out of ' + str(len(totalHostsList)) + ' host objects are unused')
    print('Note: There may be additional items that are members of unused groups.  Unused groups need to be removed before those members will be marked unused')
    print('\nBacking up objects....')
    netObjectsBackup(token, DUUID, 'hosts', unusedHostsList)
    if (input("Do you want to delete unused host objects? (y/n)") == 'y'):
        print('Deleting objects....')
        for item in unusedHostsList:
            result = deleteObject(token, DUUID, 'hosts', item['id'])
            if 'error' in result.keys():
                out_str = 'Unable to delete host object ' + item['name'] + ' Error: ' + result['error']['messages'][0]['description']
                logging(out_str)
        print('\nGathering updated oject information....')
        totalHostsList = netObjectsList(token, DUUID, 'hosts')
        unusedHostsList = unusednetObjectsList(token, DUUID, 'hosts')
        hosts_after = len(unusedHostsList)
        print(str(len(unusedHostsList)) + ' out of ' + str(len(totalHostsList)) + ' host objects are unused')
    else:
        hosts_after = hosts_before
    
    #summary output
    groups_removed = groups_before - groups_after
    networks_removed = networks_before - networks_after
    ranges_removed = ranges_before - ranges_after
    hosts_removed = hosts_before - hosts_after
    
    logging(separator)
    logging('Unused object cleanup complete')
    logging('The following objects were removed:')
    logging('Groups: ' + str(groups_removed))
    logging('Networks: ' + str(networks_removed))
    logging('Ranges: ' + str(ranges_removed))
    logging('Hosts: ' + str(hosts_removed))
    

if __name__ == "__main__":
    main()
