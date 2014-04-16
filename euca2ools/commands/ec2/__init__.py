# Copyright 2009-2014 Eucalyptus Systems, Inc.
#
# Redistribution and use of this software in source and binary forms,
# with or without modification, are permitted provided that the following
# conditions are met:
#
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
from operator import itemgetter
import os.path
import shlex
from string import Template
import sys

from requestbuilder import Arg
from requestbuilder.auth import QuerySigV2Auth
from requestbuilder.exceptions import AuthError
from requestbuilder.mixins import TabifyingMixin
from requestbuilder.request import AWSQueryRequest
from requestbuilder.service import BaseService

from euca2ools.commands import Euca2ools
from euca2ools.exceptions import AWSError
from euca2ools.util import substitute_euca_region


class EC2(BaseService):
    NAME = 'ec2'
    DESCRIPTION = 'Elastic compute cloud service'
    API_VERSION = '2013-02-01'
    REGION_ENVVAR = 'AWS_DEFAULT_REGION'
    URL_ENVVAR = 'EC2_URL'

    ARGS = [Arg('-U', '--url', metavar='URL',
                help='compute service endpoint URL')]

    def configure(self):
        substitute_euca_region(self)
        BaseService.configure(self)

    def handle_http_error(self, response):
        raise AWSError(response)


class EC2Request(AWSQueryRequest, TabifyingMixin):
    SUITE = Euca2ools
    SERVICE_CLASS = EC2
    AUTH_CLASS = QuerySigV2Auth
    METHOD = 'POST'

    def __init__(self, **kwargs):
        AWSQueryRequest.__init__(self, **kwargs)

    def print_resource_tag(self, resource_tag, resource_id):
        resource_type = RESOURCE_TYPE_MAP.lookup(resource_id)
        print self.tabify(['TAG', resource_type, resource_id,
                           resource_tag.get('key'), resource_tag.get('value')])

    def print_reservation(self, reservation):
        res_line = ['RESERVATION', reservation['reservationId'],
                    reservation.get('ownerId')]
        # group.get('entry') is a workaround for a CLC bug
        group_ids = [group.get('groupName') or group.get('groupId') or
                     group.get('entry') or ''
                     for group in reservation['groupSet']]
        res_line.append(', '.join(group_ids))
        print self.tabify(res_line)
        for instance in sorted(reservation.get('instancesSet') or [],
                               key=itemgetter('launchTime')):
            self.print_instance(instance)

    def print_instance(self, instance):
        instance_line = ['INSTANCE']
        for key in ['instanceId', 'imageId', 'dnsName', 'privateDnsName']:
            instance_line.append(instance.get(key))
        instance_line.append(instance.get('instanceState', {})
                                     .get('name'))
        instance_line.append(instance.get('keyName'))
        instance_line.append(instance.get('amiLaunchIndex'))
        instance_line.append(','.join([code['productCode'] for code in
                             instance.get('productCodes', [])]))
        instance_line.append(instance.get('instanceType'))
        instance_line.append(instance.get('launchTime'))
        instance_line.append(instance.get('placement', {}).get(
            'availabilityZone'))
        instance_line.append(instance.get('kernelId'))
        instance_line.append(instance.get('ramdiskId'))
        instance_line.append(instance.get('platform'))
        if instance.get('monitoring'):
            instance_line.append('monitoring-' +
                                 instance['monitoring'].get('state'))
        else:
            # noinspection PyTypeChecker
            instance_line.append(None)
        instance_line.append(instance.get('ipAddress'))
        instance_line.append(instance.get('privateIpAddress'))
        instance_line.append(instance.get('vpcId'))
        instance_line.append(instance.get('subnetId'))
        instance_line.append(instance.get('rootDeviceType'))
        instance_line.append(instance.get('instanceLifecycle'))
        instance_line.append(instance.get('showInstanceRequestId'))
        # noinspection PyTypeChecker
        instance_line.append(None)  # Should be the license, but where is it?
        instance_line.append(instance.get('placement', {}).get('groupName'))
        instance_line.append(instance.get('virtualizationType'))
        instance_line.append(instance.get('hypervisor'))
        instance_line.append(instance.get('clientToken'))
        instance_line.append(','.join([group['groupId'] for group in
                                       instance.get('groupSet', [])]))
        instance_line.append(instance.get('placement', {}).get('tenancy'))
        instance_line.append(instance.get('ebsOptimized'))
        instance_line.append(instance.get('iamInstanceProfile', {}).get('arn'))
        print self.tabify(instance_line)

        for blockdev in instance.get('blockDeviceMapping', []):
            self.print_blockdevice(blockdev)

        for nic in instance.get('networkInterfaceSet', []):
            self.print_interface(nic)

        for tag in instance.get('tagSet', []):
            self.print_resource_tag(tag, instance.get('instanceId'))

    def print_blockdevice(self, blockdev):
        # Block devices belong to instances
        print self.tabify(('BLOCKDEVICE', blockdev.get('deviceName'),
                           blockdev.get('ebs', {}).get('volumeId'),
                           blockdev.get('ebs', {}).get('attachTime'),
                           blockdev.get('ebs', {}).get('deleteOnTermination'),
                           blockdev.get('ebs', {}).get('volumeType'),
                           blockdev.get('ebs', {}).get('iops')))

    def print_blockdevice_mapping(self, mapping):
        # Block device mappings belong to images
        if mapping.get('virtualName'):
            print self.tabify(('BLOCKDEVICEMAPPING', 'EPHEMERAL',
                               mapping.get('deviceName'),
                               mapping.get('virtualName')))
        else:
            ebs = mapping.get('ebs') or {}
            print self.tabify(('BLOCKDEVICEMAPPING', 'EBS',
                               mapping.get('deviceName'),
                               ebs.get('snapshotId'), ebs.get('volumeSize'),
                               ebs.get('deleteOnTermination'),
                               ebs.get('volumeType'), ebs.get('iops')))

    def print_interface(self, nic):
        nic_info = [nic.get(attr) for attr in (
            'networkInterfaceId', 'subnetId', 'vpcId', 'ownerId', 'status',
            'privateIpAddress', 'privateDnsName', 'sourceDestCheck')]
        print self.tabify(['NIC'] + nic_info)
        if nic.get('attachment'):
            attachment_info = [nic['attachment'].get(attr) for attr in (
                'attachmentID', 'deviceIndex', 'status', 'attachTime',
                'deleteOnTermination')]
            print self.tabify(['NICATTACHMENT'] + attachment_info)
        privaddresses = nic.get('privateIpAddressesSet', [])
        if nic.get('association'):
            association = nic['association']
            # The EC2 tools apparently print private IP info in the
            # association even though that info doesn't appear there
            # in the response, so we have to look it up elsewhere.
            for privaddress in privaddresses:
                if (privaddress.get('association', {}).get('publicIp') ==
                        association.get('publicIp')):
                    # Found a match
                    break
            else:
                privaddress = None
            print self.tabify(('NICASSOCIATION', association.get('publicIp'),
                               association.get('ipOwnerId'), privaddress))
        for group in nic.get('groupSet', []):
            print self.tabify(('GROUP', group.get('groupId'),
                               group.get('groupName')))
        for privaddress in privaddresses:
            print self.tabify(('PRIVATEIPADDRESS',
                               privaddress.get('privateIpAddress')))

    def print_volume(self, volume):
        vol_bits = ['VOLUME']
        for attr in ('volumeId', 'size', 'snapshotId', 'availabilityZone',
                     'status', 'createTime'):
            vol_bits.append(volume.get(attr))
        vol_bits.append(volume.get('volumeType') or 'standard')
        vol_bits.append(volume.get('iops'))
        print self.tabify(vol_bits)
        for attachment in volume.get('attachmentSet', []):
            self.print_attachment(attachment)
        for tag in volume.get('tagSet', []):
            self.print_resource_tag(tag, volume.get('volumeId'))

    def print_attachment(self, attachment):
        print self.tabify(['ATTACHMENT', attachment.get('volumeId'),
                           attachment.get('instanceId'),
                           attachment.get('device'),
                           attachment.get('status'),
                           attachment.get('attachTime')])

    def print_snapshot(self, snap):
        print self.tabify(['SNAPSHOT', snap.get('snapshotId'),
                           snap.get('volumeId'), snap.get('status'),
                           snap.get('startTime'), snap.get('progress'),
                           snap.get('ownerId'), snap.get('volumeSize'),
                           snap.get('description')])
        for tag in snap.get('tagSet', []):
            self.print_resource_tag(tag, snap.get('snapshotId'))

    def print_bundle_task(self, task):
        print self.tabify(['BUNDLE', task.get('bundleId'),
                           task.get('instanceId'),
                           task.get('storage', {}).get('S3', {}).get('bucket'),
                           task.get('storage', {}).get('S3', {}).get('prefix'),
                           task.get('startTime'), task.get('updateTime'),
                           task.get('state'), task.get('progress')])

    def print_conversion_task(self, task):
        task_bits = []
        if task.get('importVolume'):
            task_bits.extend(('TaskType', 'IMPORTVOLUME'))
        if task.get('importInstance'):
            task_bits.extend(('TaskType', 'IMPORTINSTANCE'))
        if task.get('conversionTaskId'):
            task_bits.append('TaskId'),
            task_bits.append(task.get('conversionTaskId'))
        if task.get('expirationTime'):
            task_bits.append('ExpirationTime')
            task_bits.append(task['expirationTime'])
        if task.get('state'):
            task_bits.append('Status')
            task_bits.append(task['state'])
        if task.get('statusMessage'):
            task_bits.append('StatusMessage')
            task_bits.append(task['statusMessage'])

        if task.get('importVolume'):
            print self.tabify(task_bits)
            self.__print_import_disk(task['importVolume'])
        if task.get('importInstance'):
            if task['importInstance'].get('instanceId'):
                task_bits.extend('InstanceID',
                                 task['importInstance']['instanceId'])
            print self.tabify(task_bits)
            for volume in task['importInstance'].get('volumes') or []: 
                self.__print_import_disk(volume)

    def __print_import_disk(self, container):
        disk_bits = ['DISKIMAGE']
        image = container['image'] or {}
        volume = container['volume'] or {}
        if image.get('format'):
            disk_bits.extend(('DiskImageFormat', image['format']))
        if image.get('size'):
            disk_bits.extend(('DiskImageSize', image['size']))
        if volume.get('id'):
            disk_bits.extend(('VolumeId', volume['id']))
        if volume.get('size'):
            disk_bits.extend(('VolumeSize', volume['size']))
        if container.get('availabilityZone'):
            disk_bits.extend(('AvailabilityZone',
                              container['availabilityZone']))
        if container.get('bytesConverted'):
            disk_bits.extend(('ApproximateBytesConverted',
                              container['bytesConverted']))
        if container.get('status'):
            # This is the status of the volume for an ImportInstance operation
            disk_bits.extend(('Status', container.get('status')))
        if container.get('statusMessage'):
            disk_bits.extend(('StatusMessage', container.get('statusMessage')))
        print self.tabify((disk_bits))


class _ResourceTypeMap(object):
    _prefix_type_map = {
        'cgw':    'customer-gateway',
        'dopt':   'dhcp-options',
        'aki':    'image',
        'ami':    'image',
        'ari':    'image',
        'eki':    'image',
        'emi':    'image',
        'eri':    'image',
        'i':      'instance',
        'igw':    'internet-gateway',
        'acl':    'network-acl',
        'xxx':    'reserved-instances',  # reserved instance IDs are UUIDs
        'rtb':    'route-table',
        'sg':     'security-group',
        'snap':   'snapshot',
        'sir':    'spot-instances-request',
        'subnet': 'subnet',
        'vol':    'volume',
        'vpc':    'vpc',
        'vpn':    'vpn-connection',
        'vgw':    'vpn-gateway'}

    def lookup(self, item):
        if not isinstance(item, basestring):
            raise TypeError('argument type must be str')
        for prefix in self._prefix_type_map:
            if item.startswith(prefix + '-'):
                return self._prefix_type_map[prefix]

    def __iter__(self):
        return iter(set(self._prefix_type_map.values()))

RESOURCE_TYPE_MAP = _ResourceTypeMap()
