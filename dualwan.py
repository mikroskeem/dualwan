#!/usr/bin/env python3
import sys, os, subprocess
from filelock import filelock

intone = "wlo1"
#inttwo = "wlo2"
inttwo = "wlp0s29u1u2"
rt_table = "/etc/iproute2/rt_tables"

def setup_rt_table():
	# Initial config
	d = {"rttnumone": None, "rttnumtwo": None, "intone": intone, "inttwo": inttwo}

	# Get free routing table numbers and check if tables are defined already
	rtFile = open(rt_table, "r+")
	existingNums = []
	existingTables = []
	for k in rtFile.readlines():
		if "#" in k:
			continue
		x=k.replace("\n","").split()
		existingNums.append(x[0])
#		if "_dualwan" in x[1]:
#			existingTables.append(x[1].split("_")[0]) #TODO: moar checks on existing tables
	rtFile.close()

#	print(existingNums)
#	print(existingTables)

	gotNums = 0
	tmpNum = 0
	while True:
		if "{}".format(tmpNum) in existingNums:
			tmpNum += 1
		else:
			if gotNums == 0:                              # This place here should be replaced
				d["rttnumone"] = tmpNum
				existingNums.append("{}".format(tmpNum))
				gotNums = 1
				tmpNum = 0
				continue
			elif gotNums == 1:
				d["rttnumtwo"] = tmpNum
				break

	# Format config
	conf="""# Dual WAN tables, DO NOT ADD YOUR OWN OPTIONS AFTER THESE
#
{rttnumone} {intone}_dualwan
{rttnumtwo} {inttwo}_dualwan
""".format(**d)


	# Now print it
	#print(conf) #NOPE

	# Reopen ${rt_table} in append mode 
	rtFile = open(rt_table, "a")
	rtFile.write(conf)

def remove_rt_table_setup():
	# Read everything from ${rt_table} and skip everything after Dual WAN signature
	rtFile = open(rt_table, "r")
	filebuf = ""
	has_dualwan = 0
	for k in rtFile.readlines():
		if "# Dual WAN tables, DO NOT ADD YOUR OWN OPTIONS AFTER THESE" in k:
			has_dualwan = 1
			break
		filebuf += k
	rtFile.close()
	if has_dualwan == 1: #No need to rewrite file if no need (TODO: Better explanation)
		# Delete file and reopen in write mode
		os.unlink(rt_table)
		with filelock.FileLock(rt_table):
			rtFile = open(rt_table, "w")
			rtFile.write(filebuf)
			rtFile.close()

def get_intf_mac(intf):
	proc = subprocess.Popen(["ip", "link", "show", intf], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	procout,procerr = proc.communicate()
	mac = ""
	if len(procout.decode()) > 1:
		for k in procout.decode().split("\n"):
			if "link" in k:
				mac = k.split()[1]
				break
	else:
		mac = procerr.decode().replace("\n","")
	return mac

def get_intf_ip(intf, ip6):
	proc = subprocess.Popen(["ip", "address", "show", "dev", intf], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	ips = []
	procout,procerr = proc.communicate()
	if len(procout.decode()) > 1:
		for k in procout.decode().split("\n"):
			if "inet" in k:
				data = k.split()
				if data[0] == "inet6":
					continue
				type = ("IPv4" if data[0] == "inet" else "IPv6") #TODO: do something useful with IPv6
				addr,prefix = data[1].split("/")
				ips.append({"type": type, "ip": addr, "prefix": prefix})
	else:
		ips.append(procerr.decode().replace("\n",""))
	return ips

def get_intf_route(intf):
	proc = subprocess.Popen(["ip", "route"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	procout,procerr = proc.communicate()
	routes = []
	if len(procout.decode()) > 1:
		for k in procout.decode().split("\n"):
			line = k.split()
			if len(line) < 1:
				continue
			elif line[0] == "default" and len(line) > 1 and (line[0] + " " + line[1]) == "default via" and line[4] == intf:
				routes.append({"intf": line[4], "route": line[2]})
				continue
			elif line[0] == "nexthop" and line[4] == intf:
				routes.append({"intf": "dualwan|{}".format(line[4]), "route": line[2]})
	else:
		routes.append("No routes, check connection.")
	if len(routes) < 1:
		routes.append("No such interface.")
	print(routes)
	return routes

# Debug shit
#print("intone:", get_intf_ip(intone, False))
#print("inttwo:", get_intf_ip(inttwo, False))
#print("intone:", get_intf_mac(intone))
#print("inttwo:", get_intf_mac(inttwo))
#print("intone:", get_intf_route(intone))
#print("inttwo:", get_intf_route(inttwo))



def setup_intf(intf):
	ipAddr = get_intf_ip(intf, False)[0]
	tmpIpPrefix = ipAddr["ip"].split(".")
	tmpIpPrefix[3] = "0/{}".format(ipAddr["prefix"])    # This place is a total mess
	ipPrefix = ".".join(tmpIpPrefix)
	ipAddr = ipAddr["ip"]
	ipRoute = get_intf_route(intf)[0]["route"]
	intfTable = "{}_dualwan".format(intf)

	route_add = ["ip", "route", "add", ipPrefix, "dev", intf, "src", ipAddr, "table", intfTable]
	route_defadd = ["ip", "route", "add", "default", "via", ipRoute, "table", intfTable]
	rule_add = ["ip", "rule", "add", "from", ipAddr, "table", intfTable]

	for k in [route_add,route_defadd,rule_add]:
		proc = subprocess.Popen(k, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		procout,procerr = proc.communicate()
		if len(procerr.decode()) > 0:
			print(procerr.decode())

	return ipRoute
		

def setup_whole_thing():
	setup_rt_table()
	intone_route = setup_intf(intone)
	inttwo_route = setup_intf(inttwo)
	cmd = ["ip", "route", "add", "default", "scope", "global", "nexthop", "via", intone_route, "dev", intone, "weight", "1", "nexthop", "via", inttwo_route, "dev", inttwo, "weight", "1"]
	proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	procout,procerr = proc.communicate()
	if len(procerr.decode()) > 0:
		print(procerr.decode())

#def stop_this_bullshit():
#	remove_rt_table_setup()

remove_rt_table_setup() # Safe to call if rt_tables haven't actually set up before
setup_whole_thing()
