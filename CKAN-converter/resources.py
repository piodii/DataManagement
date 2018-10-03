#!/usr/bin/env python

# CoeGSS
# Piotr Dzierżak pdzierzak@icis.pcz.pl PSNC

import urllib2
import urllib
import json
import requests

SSL_VERIFY = 0

def create_resource(ckan_url, api_key, package_id, name, file_path):
    r = requests.post(ckan_url,
                      verify=SSL_VERIFY,
                      data={'package_id': package_id,
                            'url': 'upload',
                            'name': name},
                      headers={'Authorization': api_key},
                      files={'upload': open(file_path, 'rb')}
                      )

    if r.status_code != 200:
        print('Error while creating resource: {0}'.format(r.content))
#    else:
#        print('OK: {0}'.format(r.content))

    print('Success: {0}'.format(r.json().get('success')))
    return r.json().get('success')
