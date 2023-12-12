# this script will restore objects previously deleted using fmc-cleanup-unused-objects.py
# the script assumes the objects were all recently deleted and can be recreated as-was without issue.  

# BASE_URL needs to be updated with the FMC url/ip

# Developed and tested with the following environment
# - OS: linux
# - Python: 3.6.8
# - Target platform:  FMC 7.0.4
# - Dependencies: backup files from fmc-cleanup-unused-objects.py
# - Other comments: this script has undergone very minimal testing in a lab environment and may not account for all production scenerios



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
# Backup files created by cleanup script embed date in the filename which needs to be removed from the filename before using as input file to this script
group_file = 'FMC-network-group-object-backup.csv'
host_file = 'FMC-hosts-object-backup.csv'
net_file = 'FMC-networks-object-backup.csv'
range_file = 'FMC-ranges-object-backup.csv'
logFile = 'fmc-object-restore.log'


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

# get all network objects
# FMC limits the number of responses to a query so mulitiple queries are required
# each subsequent query will have the offset incremented by the limit and the results appended to a single list
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
    raw = response.json()
    p = raw['paging']['pages']
    
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

# function to return a single list of all network, host, range and group objects in FMC
def FMCobjectsList(token, DUUID):

    allObjects = []
    net = netObjectsList(token, DUUID, 'networks')
    host = netObjectsList(token, DUUID, 'hosts')
    range = netObjectsList(token, DUUID, 'ranges')
    group = netObjectsList(token, DUUID, 'networkgroups')
    allObjects = net + host + range + group
    
    return allObjects

    
#creates host, range or network objects.  initially the bulk method was tried to create
#all objects in a single call but should FMC have an issue creating any single item in the bulk request
#it rejects/fails the entire request.  this function will create each object one at a time to avoid
#complete failure. this does however require a lot of API calls and there for check/pause when request limit reached
def createObjects(token, DUUID, objType, objList):

    for obj in objList:
        out_str = 'creating' + objType + 'object' + obj['name'] + obj['value']
        logging(out_str)
        dict = {'name':obj['name'], 'description':obj['description'], 'type':obj['type'], 'value':obj['value']}
        payload = json.dumps(dict)
        response = requests.post(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
            headers={'Content-Type': 'application/json', 'X-auth-access-token':token},
            data=payload,
            verify=False,
            )
            
        if response.status_code == 429:
            print('request limit reached. pausing 1 minute')
            time.sleep(61)
            response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/' + objType,
            headers={'Content-Type': 'application/json', 'X-auth-access-token':token},
            data=payload,
            verify=False,
            )
            
        if response.status_code == 201:
            out_str = objType + ' object creation complete'
            logging(out_str)
        else:
            result = response.json()
            out_str = 'object creation failed:' + result['error']['messages'][0]['description']
            logging(out_str)



#create groups in reverse order they were deleted in order to create child objects prior to parent objects
def createGroups(token, DUUID, groups):

    group_objects = []
    current_pass = 1000 #set to arbitrary large number
    groups = sortGroups(groups) #sort groups by 'pass' number so last deleted are first created
    for group in groups:
        if group['pass'] < current_pass:
            current_pass = group['pass']
            fmc_objects = FMCobjectsList(token, DUUID) #if working on a new pass, get fresh objects list to include those created on last pass
        out_str = 'Creating group ' + group['name']
        logging(out_str)
        new_group = {'name':group['name'],'description':group['description'], 'type':'NetworkGroup'}
        #get all child objects that belong in this new group
        if len(group['objects']) > 0:
            for member in group['objects']:
                found = False
                for object in fmc_objects:
                    if member == object['name']:
                        found = True
                        break
                if found:
                    group_objects.append({'type':object['type'], 'name':object['name'], 'id':object['id']})
                else:
                    out_str = '\ngroup ' + group['name'] + ' member ' + member + ' not found in fmc objects'
                    logging(out_str)
            new_group['objects'] = group_objects
        #get all child literals that belong in this new group
        if len(group['literals']) > 0:
            new_group['literals'] = group['literals']
        payload = json.dumps(new_group)
        response = requests.post(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/networkgroups',
            headers={'Content-Type': 'application/json', 'X-auth-access-token':token},
            data=payload,
            verify=False,
            )
        if response.status_code == 429:
            print('request limit reached. pausing 1 minute')
            time.sleep(61)
            response = requests.get(
            BASE_URL + '/api/fmc_config/v1/domain/' + DUUID + '/object/networkgroups',
            headers={'Content-Type': 'application/json', 'X-auth-access-token':token},
            data=payload,
            verify=False,
            )
        if response.status_code == 201:
            out_str = 'group' + group['name'] + ' creation complete'
            logging(out_str)
        else:
            result = response.json()
            out_str = 'group' + group['name'] + ' creation failed' + result['error']['messages'][0]['description']
            logging(out_str)
        new_group.clear()
        group_objects.clear()

#sort object list in reverse order by key, in this case 'pass' count
#this will facilitate recreating groups in reverse order they were deleted
#so that child objects will be created prior to parent objects     
def sortGroups(groups):
    groups.sort(reverse=True, key=sortKey)
    return groups

#return the value of 'pass' for sorting
def sortKey(e):
    return e['pass']

#log output to file and console
def logging(out_str):
    print(out_str)
    with open(logFile, "a") as file:
        file.write(out_str + '\n')


# group members in group backup file are stored in an unusable format
# during backup the list is flattened to a string and stored in a single cell
# due to the formating and punctuation used when flattening to string, this data cannot be converted back to a list as-is
# this function performs the work required to convert the string and return it in list format
def strToList(str):

    reformat = str.replace("\'", "\"")
    return json.loads(reformat)


def main():

    # lists of dictionary objects
    groups = []
    hosts = []
    nets = []
    ranges = []
    separator = '\n---------------------------------------------------'

    result = login()
    token = result.get('X-auth-access-token')
    DUUID = result.get('DOMAIN_UUID')
    
    #create empty log file
    with open(logFile, "w") as file:
        pass
        
    #restore host objects
    logging(separator)
    if os.path.isfile(host_file):
        print(host_file + ' found')
        with open(host_file, "r") as file:
            reader = csv.reader(file)
            for row in reader:
                hosts.append({"name": row[0].strip(),
                                "description": row[1].strip(),
                                "type": row[2].strip(),
                                "value":row[3].strip()})
        createObjects(token, DUUID, 'hosts', hosts)
    else:
        print(host_file + ' not present. skipping restore')
    
    #restore range objects
    logging(separator)
    if os.path.isfile(range_file):
        print(range_file + ' found')
        with open(range_file, "r") as file:
            reader = csv.reader(file)
            for row in reader:
                ranges.append({"name": row[0].strip(),
                                "description": row[1].strip(),
                                "type": row[2].strip(),
                                "value":row[3].strip()})
        createObjects(token, DUUID, 'ranges', ranges)
    else:
        print(range_file + ' not present. skipping restore')
    
    #restore network objects
    logging(separator)
    if os.path.isfile(net_file):
        print(net_file + ' found')
        with open(net_file, "r") as file:
            reader = csv.reader(file)
            for row in reader:
                nets.append({"name": row[0].strip(),
                                "description": row[1].strip(),
                                "type": row[2].strip(),
                                "value":row[3].strip()})
        createObjects(token, DUUID, 'networks', nets)
    else:
        print(net_file + ' not present. skipping restore')
    
    #restore group objects
    logging(separator)
    if os.path.isfile(group_file):
        print(group_file + ' found')
        with open(group_file, "r") as file:
            reader = csv.reader(file)
            for row in reader:
                groups.append({"name": row[0].strip(),
                                "description": row[1].strip(),
                                "type": row[2].strip(),
                                "objects":strToList(row[3].strip()),
                                "literals":strToList(row[4].strip()),
                                "pass":strToList(row[5])})
        createGroups(token, DUUID, groups)
    else:
        print(group_file + ' not present. skipping restore')
    


if __name__ == "__main__":
    main()
