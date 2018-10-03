# CoeGSS
# Piotr Dzierżak pdzierzak@icis.pcz.pl PSNC

import socket
import json
import subprocess
import datetime
import os

class CkCheck:
    nginx = ""
    ckan = ""
    postgres = ""
    datapusher = ""
    memcached = ""
    solr = ""
    disk = ""
    status = ""
    message = ""

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def toXml(self):
        now = datetime.datetime.now()
        out = '<healthdata date="{}" status="{}" message="{}">\n'.format(now.strftime("%d/%m/%Y %H:%M:%S"), self.status, self.message)
        out = out + '\t<nginx status="{}" />\n'.format(self.nginx)
        out = out + '\t<ckan status="{}" />\n'.format(self.ckan)
        out = out + '\t<postgres status="{}" />\n'.format(self.postgres)
        out = out + '\t<datapusher status="{}" />\n'.format(self.datapusher)
        out = out + '\t<memcached status="{}" />\n'.format(self.memcached)
        out = out + '\t<solr status="{}" />\n'.format(self.solr)
        out = out + '\t<disk status="{}" usage="{}%" />\n'.format(("critical" if self.disk > 95 else ("warning" if self.disk > 80 else "ok")), self.disk)
        out = out + '</healthdata>\n'
        return out

def diskStat(partition):
    disk = os.statvfs(partition)
    percent = (disk.f_blocks - disk.f_bfree) * 100 / (disk.f_blocks -disk.f_bfree + disk.f_bavail) + 1
    return round(percent, 2)


chk = CkCheck()
chk.status = "ok"

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',80))
if result == 0:
    print("Port 80 is open")
    chk.nginx = "ok"
else:
    print("Port 80 is not open")
    chk.nginx = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Nginx is down"
    chk.status = "critical"
sock.close()

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',8080))
if result == 0:
    print("Port 8080 is open")
    chk.ckan = "ok"
else:
    print ("Port 8080 is not open")
    chk.ckan = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "CKAN is down"
    if chk.status == "ok":
        chk.status = "critical"
sock.close()

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',5432))
if result == 0:
    print("Port 5432 is open")
    chk.postgres = "ok"
else:
    print("Port 5432 is not open")
    chk.postgres = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Postgres is down"
    if chk.status == "ok":
        chk.status = "critical"
sock.close()

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',8800))
if result == 0:
    print("Port 8800 is open")
    chk.datapusher = "ok"
else:
    print("Port 8800 is not open")
    chk.datapusher = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Datapusher is down"
    if chk.status == "ok":
        chk.status = "critical"
sock.close()

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',11211))
if result == 0:
    print("Port 11211 is open")
    chk.memcached = "ok"
else:
    print("Port 11211 is not open")
    chk.memcached = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Memcached is down"
    if chk.status == "ok":
        chk.status = "critical"
sock.close()


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1',8983))
if result == 0:
    print("Port 8983 is open")
    chk.solr = "ok"
else:
    print("Port 8983 is not open")
    chk.solr = "critical"
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Solr is down"
    if chk.status == "ok":
        chk.status = "critical"
sock.close()


chk.disk = diskStat("/")
if chk.disk > 95:
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Disk usage {}%".format(chk.disk)
    if chk.status == "ok":
        chk.status = "critical"
elif chk.disk > 80:
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Disk usage {}%".format(chk.disk)
    if chk.status == "ok":
        chk.status = "warning"


# start / stop nginx service - CKAN node up or down
if chk.nginx == "ok" and chk.status == "critical":
    os.system("service nginx stop")
    print("Stop nginx ... \n")
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Stopping nginx"
elif chk.nginx == "critical" and chk.ckan == "ok" and chk.datapusher == "ok" and chk.postgres == "ok" and chk.solr == "ok" and chk.memcached == "ok" and chk.disk <= 95:
    os.system("service nginx start")
    print("Start nginx ... \n")
    chk.message = chk.message + ("; " if chk.message != "" else "") + "Starting nginx"

print(chk.toXml())

outFile = open("/var/www/ckan-checker/ckan-status.xml", "w")
outFile.write(chk.toXml())
outFile.close()
