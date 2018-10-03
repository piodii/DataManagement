# -*- coding: utf-8 -*-
from __future__ import unicode_literals

# CoeGSS
# Piotr Dzierżak pdzierzak@icis.pcz.pl PSNC
# Original CKAN jobs.py file modified to convert input rows to a HDF5 format and upload new H5 file to a dataset

import json
import urllib2
import socket
import requests
import urlparse
import itertools
import datetime
import locale
import pprint
import logging
import decimal
import hashlib
import cStringIO
import time

import messytables
from slugify import slugify

import ckanserviceprovider.job as job
import ckanserviceprovider.util as util
from ckanserviceprovider import web

#
import resources
import h5py
import numpy
import os
import time
from h5py.h5s import NULL
#

if locale.getdefaultlocale()[0]:
    lang, encoding = locale.getdefaultlocale()
    locale.setlocale(locale.LC_ALL, locale=(lang, encoding))
else:
    locale.setlocale(locale.LC_ALL, '')

## set parameters from a config file
MAX_CONTENT_LENGTH = web.app.config.get('MAX_CONTENT_LENGTH') or 10485760
DOWNLOAD_TIMEOUT = web.app.config.get('DOWNLOAD_TIMEOUT') or 30
##

if web.app.config.get('SSL_VERIFY') in ['False', 'FALSE', '0']:
    SSL_VERIFY = False
else:
    SSL_VERIFY = True

if not SSL_VERIFY:
    requests.packages.urllib3.disable_warnings()

_TYPE_MAPPING = {
    'String': 'text',
    # 'int' may not be big enough,
    # and type detection may not realize it needs to be big
    'Integer': 'numeric',
    'Decimal': 'numeric',
    'DateUtil': 'timestamp'
}

_TYPES = [messytables.StringType, messytables.DecimalType,
          messytables.IntegerType, messytables.DateUtilType]

TYPE_MAPPING = web.app.config.get('TYPE_MAPPING', _TYPE_MAPPING)
TYPES = web.app.config.get('TYPES', _TYPES)

DATASTORE_URLS = {
    'datastore_delete': '{ckan_url}/api/action/datastore_delete',
    'resource_update': '{ckan_url}/api/action/resource_update'
}

class HTTPError(util.JobError):
    """Exception that's raised if a job fails due to an HTTP problem."""

    def __init__(self, message, status_code, request_url, response):
        """Initialise a new HTTPError.

        :param message: A human-readable error message
        :type message: string

        :param status_code: The status code of the errored HTTP response,
            e.g. 500
        :type status_code: int

        :param request_url: The URL that was requested
        :type request_url: string

        :param response: The body of the errored HTTP response as unicode
            (if you have a requests.Response object then response.text will
            give you this)
        :type response: unicode

        """
        super(HTTPError, self).__init__(message)
        self.status_code = status_code
        self.request_url = request_url
        self.response = response

    def as_dict(self):
        """Return a JSON-serializable dictionary representation of this error.

        Suitable for ckanserviceprovider to return to the client site as the
        value for the "error" key in the job dict.

        """
        if self.response and len(self.response) > 200:
            response = self.response[:200] + '...'
        else:
            response = self.response
        return {
            "message": self.message,
            "HTTP status code": self.status_code,
            "Requested URL": self.request_url,
            "Response": response,
        }

    def __str__(self):
        return u'{} status={} url={} response={}'.format(
            self.message, self.status_code, self.request_url, self.response) \
            .encode('ascii', 'replace')


def get_url(action, ckan_url):
    """
    Get url for ckan action
    """
#    if not urlparse.urlsplit(ckan_url).scheme:
#        ckan_url = 'http://' + ckan_url.lstrip('/')
#    ckan_url = ckan_url.rstrip('/')
#    return '{ckan_url}/api/3/action/{action}'.format(
#        ckan_url=ckan_url, action=action)
# fix to send data locally
    return 'http://127.0.0.1/api/3/action/{action}'.format(
        action=action)

def check_response(response, request_url, who, good_status=(201, 200), ignore_no_success=False):
    """
    Checks the response and raises exceptions if something went terribly wrong

    :param who: A short name that indicated where the error occurred
                (for example "CKAN")
    :param good_status: Status codes that should not raise an exception

    """
    if not response.status_code:
        raise HTTPError(
            'DataPusher received an HTTP response with no status code',
            status_code=None, request_url=request_url, response=response.text)

    message = '{who} bad response. Status code: {code} {reason}. At: {url}.'
    try:
        if not response.status_code in good_status:
            json_response = response.json()
            if not ignore_no_success or json_response.get('success'):
                try:
                    message = json_response["error"]["message"]
                except Exception:
                    message = message.format(
                        who=who, code=response.status_code,
                        reason=response.reason, url=request_url)
                raise HTTPError(
                    message, status_code=response.status_code,
                    request_url=request_url, response=response.text)
    except ValueError as err:
        message = message.format(
            who=who, code=response.status_code, reason=response.reason,
            url=request_url, resp=response.text[:200])
        raise HTTPError(
            message, status_code=response.status_code, request_url=request_url,
            response=response.text)


def chunky(iterable, n):
    """
    Generates chunks of data that can be loaded into ckan

    :param n: Size of each chunks
    :type n: int
    """
    it = iter(iterable)
    item = list(itertools.islice(it, n))
    while item:
        yield item
        item = list(itertools.islice(it, n))


class DatastoreEncoder(json.JSONEncoder):
    # Custon JSON encoder
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return str(obj)

        return json.JSONEncoder.default(self, obj)


def delete_datastore_resource(resource_id, api_key, ckan_url):
    try:
        delete_url = get_url('datastore_delete', ckan_url)
        response = requests.post(delete_url,
                                 verify=SSL_VERIFY,
                                 data=json.dumps({'id': resource_id,
                                                  'force': True}),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': api_key}
                                 )
        check_response(response, delete_url, 'CKAN',
                       good_status=(201, 200, 404), ignore_no_success=True)
    except requests.exceptions.RequestException:
        raise util.JobError('Deleting existing datastore failed.')


def datastore_resource_exists(resource_id, api_key, ckan_url):
    try:
        search_url = get_url('datastore_search', ckan_url)
        response = requests.post(search_url,
                                 verify=SSL_VERIFY,
                                 params={'id': resource_id,
                                         'limit': 0},
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': api_key}
                                 )
        if response.status_code == 404:
            return False
        elif response.status_code == 200:
            return response.json().get('result', {'fields': []})
        else:
            raise HTTPError(
                'Error getting datastore resource.',
                response.status_code, search_url, response,
            )
    except requests.exceptions.RequestException as e:
        raise util.JobError(
            'Error getting datastore resource ({!s}).'.format(e))


def send_resource_to_datastore(resource, headers, records, api_key, ckan_url):
    """
    Stores records in CKAN datastore
    """
    request = {'resource_id': resource['id'],
               'fields': headers,
               'force': True,
               'records': records}

    name = resource.get('name')
    url = get_url('datastore_create', ckan_url)
    r = requests.post(url,
                      verify=SSL_VERIFY,
                      data=json.dumps(request, cls=DatastoreEncoder),
                      headers={'Content-Type': 'application/json',
                               'Authorization': api_key}
                      )
    check_response(r, url, 'CKAN DataStore')


def update_resource(resource, api_key, ckan_url):
    """
    Update webstore_url and webstore_last_updated in CKAN
    """

    resource['url_type'] = 'datapusher'

    url = get_url('resource_update', ckan_url)
    r = requests.post(
        url,
        verify=SSL_VERIFY,
        data=json.dumps(resource),
        headers={'Content-Type': 'application/json',
                 'Authorization': api_key}
    )

    check_response(r, url, 'CKAN')


def get_resource(resource_id, ckan_url, api_key):
    """
    Gets available information about the resource from CKAN
    """
    url = get_url('resource_show', ckan_url)
    r = requests.post(url,
                      verify=SSL_VERIFY,
                      data=json.dumps({'id': resource_id}),
                      headers={'Content-Type': 'application/json',
                               'Authorization': api_key}
                      )
    check_response(r, url, 'CKAN')

    return r.json()['result']


def validate_input(input):
    # Especially validate metdata which is provided by the user
    if not 'metadata' in input:
        raise util.JobError('Metadata missing')

    data = input['metadata']

    if not 'resource_id' in data:
        raise util.JobError('No id provided.')
    if not 'ckan_url' in data:
        raise util.JobError('No ckan_url provided.')
    if not input.get('api_key'):
        raise util.JobError('No CKAN API key provided')


@job.async
def push_to_datastore(task_id, input, dry_run=False):
    '''Download and parse a resource push its data into CKAN's DataStore.

    An asynchronous job that gets a resource from CKAN, downloads the
    resource's data file and, if the data file has changed since last time,
    parses the data and posts it into CKAN's DataStore.

    :param dry_run: Fetch and parse the data file but don't actually post the
        data to the DataStore, instead return the data headers and rows that
        would have been posted.
    :type dry_run: boolean

    '''
    handler = util.StoringHandler(task_id, input)
    logger = logging.getLogger(task_id)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    validate_input(input)

    data = input['metadata']

    ckan_url = data['ckan_url']
    resource_id = data['resource_id']
    api_key = input.get('api_key')

    try:
        resource = get_resource(resource_id, ckan_url, api_key)
    except util.JobError, e:
        #try again in 5 seconds just incase CKAN is slow at adding resource
        time.sleep(5)
        resource = get_resource(resource_id, ckan_url, api_key)
        
    # check if the resource url_type is a datastore
    if resource.get('url_type') == 'datastore':
        logger.info('Dump files are managed with the Datastore API')
        return

    # fetch the resource data
    logger.info('Fetching from: {0}'.format(resource.get('url')))
    try:
        request = urllib2.Request(resource.get('url'))

        if resource.get('url_type') == 'upload':
            # If this is an uploaded file to CKAN, authenticate the request,
            # otherwise we won't get file from private resources
            request.add_header('Authorization', api_key)

        response = urllib2.urlopen(request, timeout=DOWNLOAD_TIMEOUT)
    except urllib2.HTTPError as e:
        raise HTTPError(
            "DataPusher received a bad HTTP response when trying to download "
            "the data file", status_code=e.code,
            request_url=resource.get('url'), response=e.read())
    except urllib2.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise util.JobError('Connection timed out after %ss' %
                                DOWNLOAD_TIMEOUT)
        else:
            raise HTTPError(
                message=str(e.reason), status_code=None,
                request_url=resource.get('url'), response=None)

    cl = response.info().getheader('content-length')
    if cl and int(cl) > MAX_CONTENT_LENGTH:
        raise util.JobError(
            'Resource too large to download: {cl} > max ({max_cl}).'.format(
            cl=cl, max_cl=MAX_CONTENT_LENGTH))

    ct = response.info().getheader('content-type').split(';', 1)[0]

    file_content = response.read()
    #logger.info(file_content)
    f = cStringIO.StringIO(file_content)
    ##

    #f = cStringIO.StringIO(response.read())
    file_hash = hashlib.md5(f.read()).hexdigest()
    f.seek(0)

    if (resource.get('hash') == file_hash
            and not data.get('ignore_hash')):
        logger.info("The file hash hasn't changed: {hash}.".format(
            hash=file_hash))
        return

    resource['hash'] = file_hash

    try:
        table_set = messytables.any_tableset(f, mimetype=ct, extension=ct)
    except messytables.ReadError as e:
        ## try again with format
        f.seek(0)
        try:
            format = resource.get('format')
            table_set = messytables.any_tableset(f, mimetype=format, extension=format)
        except:
            raise util.JobError(e)

    row_set = table_set.tables.pop()
    offset, headers = messytables.headers_guess(row_set.sample)

    existing = datastore_resource_exists(resource_id, api_key, ckan_url)
    existing_info = None
    if existing:
        existing_info = dict((f['id'], f['info'])
            for f in existing.get('fields', []) if 'info' in f)

    # Some headers might have been converted from strings to floats and such.
    headers = [unicode(header) for header in headers]

    row_set.register_processor(messytables.headers_processor(headers))
    row_set.register_processor(messytables.offset_processor(offset + 1))
    types = messytables.type_guess(row_set.sample, types=TYPES, strict=True)

    # override with types user requested
    if existing_info:
        types = [{
            'text': messytables.StringType(),
            'numeric': messytables.DecimalType(),
            'timestamp': messytables.DateUtilType(),
            }.get(existing_info.get(h, {}).get('type_override'), t)
            for t, h in zip(types, headers)]

    row_set.register_processor(messytables.types_processor(types))

    headers = [header.strip() for header in headers if header.strip()]
    headers_set = set(headers)

    def row_iterator():
        for row in row_set:
            data_row = {}
            for index, cell in enumerate(row):
                column_name = cell.column.strip()
                if column_name not in headers_set:
                    continue
                data_row[column_name] = cell.value
            yield data_row
    result = row_iterator()

    '''
    Delete existing datstore resource before proceeding. Otherwise
    'datastore_create' will append to the existing datastore. And if
    the fields have significantly changed, it may also fail.
    '''
    if existing:
        logger.info('Deleting "{res_id}" from datastore.'.format(
            res_id=resource_id))
        delete_datastore_resource(resource_id, api_key, ckan_url)

    headers_dicts = [dict(id=field[0], type=TYPE_MAPPING[str(field[1])])
                     for field in zip(headers, types)]


    # Maintain data dictionaries from matching column names
    if existing_info:
        for h in headers_dicts:
            if h['id'] in existing_info:
                h['info'] = existing_info[h['id']]
                # create columns with types user requested
                type_override = existing_info[h['id']].get('type_override')
                if type_override in _TYPE_MAPPING.values():
                    h['type'] = type_override

    logger.info('Determined headers and types: {headers}'.format(
        headers=headers_dicts))

    if dry_run:
        return headers_dicts, result

    input_format = resource.get('format')
    start_time = time.time()
    #logger.info('Informacje o zasobie: {iii}'.format(iii=resource))
    package_id = resource.get('package_id')
    file_name = resource.get('name')
    if(len(file_name) == 0):
        file_name = resource.get('url').split("/")[-1]
        #logger.info('Nie ustawiono nazwy zasobu, pobieram nazwe z urla')

    #logger.info('Potrzebne parametry: package_id: {pid}, api_key: {apk}, name: {nm}'.format(pid=package_id, apk=api_key, nm=file_name))



    #logger.info('headers_dicts: {iii}'.format(iii=headers_dicts))
    COL_COUNT = len(headers_dicts)
    #logger.info('COL_COUNT: {c}'.format(c=COL_COUNT))
    MAX_STR_LENS = [32 for x in range(0, COL_COUNT)]
    #logger.info("MAX_STR_LENS: {m}".format(m=MAX_STR_LENS))
    AVG_STR_LENS = [0 for x in range(0, COL_COUNT)]
    #logger.info("AVG_STR_LENS: {a}".format(a=AVG_STR_LENS))
    COL_TYPES = ['STRING' for x in range(0, COL_COUNT)]
    #logger.info("COL_TYPES: {ct}".format(ct=COL_TYPES))

    def to_numpy_type_tuple(col_name, col_type, max_str_len):
        if col_type == 'STRING':
            return (col_name, numpy.str_, max_str_len)
        elif col_type == 'FLOAT':
            return (col_name, 'f')
        elif col_type == 'INT':
            return (col_name, 'i')
        else:
            raise ValueError

    TABLE_TYPE = numpy.dtype([to_numpy_type_tuple(str(headers_dicts[i]['id']), COL_TYPES[i], MAX_STR_LENS[i]) for i in range(0, COL_COUNT)])
    #logger.info("TABLE_TYPE: {ct}".format(ct=TABLE_TYPE))

    H5_FILE_PATH = "/tmp/{fi}.h5".format(fi=file_name)
    if os.path.isfile(H5_FILE_PATH):
        os.remove(H5_FILE_PATH)

    H5_FILE = h5py.File(H5_FILE_PATH, 'w')
    H5_DSET = H5_FILE.create_dataset('data', (10000000,), dtype = TABLE_TYPE, chunks=True, compression="gzip")

    H5_IDX = 0
    count = 0
    for i, records in enumerate(chunky(result, 250)):
        count += len(records)
        logger.info('Saving chunk {number}'.format(number=i))
        send_resource_to_datastore(resource, headers_dicts,
                                   records, api_key, ckan_url)
        #logger.info('records: {rr}'.format(rr=records))
        for record in records:
            #logger.info('record[{idx}] : {rr}'.format(idx=H5_IDX, rr=record))
            ROW_TAB = [(v.encode('utf-8') if isinstance(v, basestring) else v) for v in record.values()]
            #logger.info('ROW_TAB[idx] : {rr}'.format(idx=H5_IDX, rr=ROW_TAB))
            H5_DSET.resize(H5_IDX + 1, 0)
            H5_DSET[H5_IDX] = tuple(ROW_TAB)
            H5_IDX = H5_IDX + 1

    H5_FILE.close()
    logger.info('Convertion to database and HDF5 file took {s} seconds'.format(s=(time.time() - start_time)))

    start_time = time.time()
    #logger.info('Uploading file HDF5 {fi} to the dataset "{res_id}"'.format(fi=(file_name + ".h5"), res_id=resource_id))
    resources.create_resource("http://127.0.0.1/api/3/action/resource_create", api_key, package_id, (file_name + ".h5"), H5_FILE_PATH)
    logger.info('Successfully uploaded file "{f}" to dataset "{res_id}" in {s} seconds'.format(res_id=resource_id, s=(time.time() - start_time), f=(file_name + ".h5")))

    if os.path.isfile(H5_FILE_PATH):
        os.remove(H5_FILE_PATH)

    logger.info('Successfully pushed {n} entries to "{res_id}".'.format(
        n=count, res_id=resource_id))

    if data.get('set_url_type', False):
        update_resource(resource, api_key, ckan_url)