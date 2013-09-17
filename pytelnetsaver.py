#!/usr/local/bin/python
import sys, traceback, os
import telnetlib
import re
import time
import threading 
import math
import datetime
import threading
import logging
import select
import random
import gzip
import ConfigParser
from optparse import OptionParser, OptionGroup
from multiprocessing import Process

class TelnetLogSaver(telnetlib.Telnet):
	''' Thread that connects to a host by telnet and starts to save 
	to a file all messages readed.
	'''
	
	def __init__(self, id, hostname,ip,filename, options):
		self.id = id 
		self.hostname = hostname
		self.ip = ip
		self.filename = filename

		# Config file options
		self.user = options["telnet"]["user"]
		self.password = options["telnet"]["password"]
		self.prompt = options["telnet"]["prompt"]
		self.max_wait_time = options["telnet"]["max_wait_time"]
		self.timeout = options["telnet"]["timeout"]
		self.expected_user_string = options["telnet"]["expected_user_string"]
		self.expected_password_string = options["telnet"]["expected_password_string"]
		self.first_prompt = options["telnet"]["first_prompt"]
		self.initial_newline = options["telnet"]["initial_newline"]
		self.telnet_debug = options["telnet"]["telnet_debug"]
		self.max_file_size = options["output"]["max_file_size"]
		
		# Open the file for append
		self.f = open(self.filename,"a")
		
		# Start the telnet session
		telnetlib.Telnet.__init__(self,ip,23,10)
		self.init()
		
		# To store the filesize
		self.filesize = self.get_filesize()
	
	def get_filesize(self):
		self.debug("checking file size")
		current_size = os.stat(self.filename).st_size
		self.debug("Filesize for now is %d bytes" % current_size)
		return current_size

	def info(self, msg):
		logging.info("%d [%s] - %s" % (self.id,self.hostname,msg))
	
	def debug(self, msg):
		logging.debug("%d [%s] - %s" % (self.id,self.hostname,msg))
	
	def error(self, msg):
		logging.error("%d [%s] - %s" % (self.id,self.hostname,msg))
		
	def option_negociation(self, socket, command, option):
		logging.debug("dummy option_negociation")
	
	def check_and_rotate(self):
		''' Check the file size and rotate if necessary '''

		self.debug("Filesize for now is %d" % self.filesize)
		if self.filesize > self.max_file_size:
			self.info("'output.max_file_size' exceeded - rotating file")
			
			# Closing the file
			self.f.close()
			
			# Get the file number
			self.debug("getting the file number")
			path = os.path.dirname(self.filename)
			basename = os.path.basename(self.filename)
			files = [ f for f in os.listdir(path) if (os.path.join(path,f) and f.startswith(basename))]
			new_filename = os.path.join(path, "%s.%d.gz" % (basename, 1+len(files)))
			
			logging.debug("creating new file '%s'" % new_filename)
			
			# Compress the file
			self.debug("moving and compressing the file")
			f_in = open(self.filename, 'rb')
			f_out = gzip.open(new_filename, 'wb')
			f_out.writelines(f_in)
			f_out.close()
			f_in.close()
			
			# reopen the file (override)
			self.debug("reopening the file (overriding)")
			self.f = open(self.filename, "w")
			self.filesize = 0
			
	
	def init(self):
		''' Connects and does additions tasks until prompt is ready'''
		# Enables telnet debugging
		if self.telnet_debug == 1:
			self.set_debuglevel(1)
		
		# workarround to avoid the connection getting stuck at option negociation
		self.set_option_negotiation_callback(self.option_negociation)
		self.debug("Connecting to %s" % ( self.ip))
		
		# first prompt
		if self.first_prompt is (not None and not ""):
			self.debug("waiting for first prompt '%s'" % self.first_prompt)
			self.read_until(self.first_prompt)	
		
		# Initial newLine
		if self.initial_newline == 1:
			self.debug("sending initial newline character")
			self.write("a\n")
		
		self.debug("waiting for '%s'" % self.expected_user_string)
		self.read_until(self.expected_user_string)
		self.write(self.user+"\n")
		
		self.debug("waiting for '%s'" % self.expected_password_string)
		self.read_until(self.expected_password_string)
		self.write(self.password+"\n")
		
		self.read_until(self.prompt)
		self.write("\n")
		self.read_until(self.prompt)
		self.debug("connected successfully, starting infinite loop to save messages")
		
		self.last_time_read = time.time()
		
	def read_and_save(self):
			
		read = ""
		self.f.write("\r\n" + datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")+"\r\n")
		# Read all the data available
		while self.sock_avail():
			e = self.read_some()
			read += e					
	
		self.f.write(read)
		self.f.flush()
		self.debug("read %d characters" % (len(read)))
		
		# Cheack antiidle
		self.anti_idle()
		
		''' At this point session is active because data has been received or 
		anti-idle has successed. Check if is necessary to rotate and compress the 
		log'''
		self.filesize += len(read)
		self.check_and_rotate()
		
		self.last_time_read = time.time()
	
	def anti_idle(self):
			
		# Anti-idle protection
		if (time.time() - self.last_time_read) > self.max_wait_time:
			''' Avoid session auto-idle'''
			self.debug("Sending intro to avoid session timeout")
			self.write("\n")
			e = self.read_until(self.prompt,3*self.timeout)
			if e is "":
				self.error("lost connection with %s" % (self.ip))
				self.close()
				self.f.close()
				return	

	
	def finish(self):
		# gracefull closing
		self.info("finishing due to kill signal, sending 'exit'")
		self.write("exit\n")	
		self.close()
		self.f.close()
		return
	

def init_logging(file,level):
	
	# Start logging
	FORMAT = "%(asctime)s - %(levelname)s: %(message)s" 
	logging.basicConfig(level=level,format=FORMAT,filename=file)
	# define a Handler which writes INFO messages or higher to the sys.stderr
	console = logging.StreamHandler()
	console.setLevel(level)
	# set a format which is simpler for console use
	formatter = logging.Formatter(FORMAT)
	# tell the handler to use this format
	console.setFormatter(formatter)
	# add the handler to the root logger
	logging.getLogger('').addHandler(console)

def parse_configfile(cfg_file):
	
	# Fields definition
	required = { 
			"telnet": [ "user","password","prompt" ],
			"logging": ["log_file"],
			"output":["output_dir"]
			}
	
	defaults = {		
			"max_wait_time": 120,
			"timeout": 5,
			"reconnect_interval": 300,
			"max_processes": -1,
			"chunk_size": 30,
			"initial_newline": 0,
			"expected_user_string": "user:",
			"expected_password_string": "password:",
			"max_file_size": 120,
			"first_prompt": "",
			"telnet_debug": 0
			}

	# Parsing config file
	config = ConfigParser.ConfigParser(defaults)
	
	config.read(cfg_file)
	
	configuration = {"telnet":{},"output":{},"logging":{}}
	
	# Telnet
	configuration["telnet"]["user"] = config.get("telnet","user")
	configuration["telnet"]["password"] = config.get("telnet","password")
	configuration["telnet"]["prompt"] = config.get("telnet","prompt").strip('"')
	configuration["telnet"]["first_prompt"] = config.get("telnet","first_prompt").strip('"')
	configuration["telnet"]["max_wait_time"] = config.getint("telnet","max_wait_time")
	configuration["telnet"]["timeout"] = config.getint("telnet","timeout")
	configuration["telnet"]["reconnect_interval"] = config.getint("telnet","reconnect_interval")
	configuration["telnet"]["max_processes"] = config.getint("telnet","max_processes")
	configuration["telnet"]["chunk_size"] = config.getint("telnet","chunk_size")
	configuration["telnet"]["initial_newline"] = config.getint("telnet","initial_newline")
	configuration["telnet"]["telnet_debug"] = config.getint("telnet","telnet_debug")
	
	configuration["telnet"]["expected_user_string"] = config.get("telnet","expected_user_string").strip('"')
	configuration["telnet"]["expected_password_string"] = config.get("telnet","expected_password_string").strip('"')
	
	# Output
	configuration["output"]["output_dir"] = config.get("output","output_dir")
	configuration["output"]["max_file_size"] = config.getint("output","max_file_size")
	
	# Logging
	configuration["logging"]["log_file"] = config.get("logging","log_file")

	# Validation and fill with defaults
	for category in ["telnet","output","logging"]:
		# Validations
		for field in required[category]:
			if field not in configuration[category]:
				raise Exception("Invalid cfg file: '%s.%s' field is required" % (category,field))
	
	return configuration

def parse_cmdline(argv):
	"""Parses the command-line."""
	
	# Manage command line arguments
	parser = OptionParser(description='pyTelnetSaver')
	parser.add_option("-c", "--cfg-file", dest="cfg_file", help="Config file (required)")
	parser.add_option("-f", "--hosts-file", dest="hosts_file", help="Target host file in CSV format (required)")
	
	# Parse the user input		  
	(options, args) = parser.parse_args()
	
	# Check required arguments
	if (options.cfg_file is None):
		parser.print_help()
		parser.error("Config file is required")
	
	if options.hosts_file is None:
		parser.print_help()
		parser.error("Host file is required")
	
	return (options, args)


def run_chunk(id,chunk,config):
	try:
		telnet_savers = []
		unavailable_savers = []
		
		# Create the array of threads
		logging.debug("creating telnet savers")
		
		t_id = 1
		for (host,ip) in chunk:
			
			host_log_file = "%s/%s.txt" % (config["output"]["output_dir"],host)
			
			try:
				t = TelnetLogSaver(t_id,host,ip,host_log_file,config)
				telnet_savers.append(t)
			except:
				logging.error("Cannot connect to host %s(%s)" % (ip,host))
				unavailable_savers.append((t_id,host,ip,host_log_file,config))
				
			t_id+=1
	
		# Init loop to wait for data to be read
		logging.info("Starting waiting loop, %d hosts (%d hosts unavailable)" % (len(telnet_savers), len(unavailable_savers)))
		last_loop = time.time()
		while len(telnet_savers)>0:
			# Wait for data on all telnets
			read_ready, write_ready, error = select.select(telnet_savers, [], [], config["telnet"]["max_wait_time"])
			
			logging.debug("P%s select returned, data from %d hosts" % (id,len(read_ready)))
			# Read and save
			for telnet in read_ready:
				try:
					telnet.read_and_save()
				except:
					logging.error("P%d - read_and_save error with host %s(%s)" %(id,telnet.ip, telnet.hostname))
					telnet_savers.remove(telnet)
					
					
			# Check anti-idle
			if (time.time() - last_loop) > config["telnet"]["max_wait_time"]:
				logging.debug("P%s checking idle periods" % (id))
				for telnet in telnet_savers:
					try:
						telnet.anti_idle()
					except:
						logging.error("P%d - anti_idle error with host %s(%s)" %(id,telnet.ip, telnet.hostname))
						telnet_savers.remove(telnet)
			
			last_loop = time.time()
			
	except KeyboardInterrupt:
			logging.info("Ctrl-c received! Sending kill to threads...")
			for t in telnet_savers:
				t.finish()
			exit(0)	

	
if __name__ == '__main__':
	
	# parse the command line
	options, args = parse_cmdline(sys.argv)
	
	# parse the cfg file
	config = parse_configfile(options.cfg_file)
	try:
		config = parse_configfile(options.cfg_file)
	except Exception as e:
		print e
		exit(0)
	
	# init logging
	init_logging(config["logging"]["log_file"], logging.INFO)

	# Read the host file
	logging.debug("parsing host file")
	file = options.hosts_file
	mapper = lambda line: (line.split(";")[0],line.split(";")[1].replace("\r\n",""))
	hosts = map(mapper, [l for l in open(file,'r')])
	random.shuffle(hosts)
	
	# Create the chunks and init the processes
	
	CHUNK_SIZE = config["telnet"]["chunk_size"]
	MAX_PROCESSES = config["telnet"]["max_processes"]
	
	if MAX_PROCESSES is -1:
		limit = len(hosts)
	else:
		MAX_HOSTS = CHUNK_SIZE * MAX_PROCESSES
		limit = len(hosts) if (len(hosts)<MAX_HOSTS) else MAX_HOSTS

	chunks = [ hosts[i:i+CHUNK_SIZE] for i in xrange(0,limit,CHUNK_SIZE)]
	
	logging.info("Starting %d processes with %d hosts per process" % (len(chunks),CHUNK_SIZE ))
	exit(0)
	# Start the processes
	try:
		processes = []
		for i in xrange(0,len(chunks)):
			chunk = chunks[i]
				
			logging.debug("Instanciando Process#%d" % i)
			
			p = Process(target=run_chunk,args=(i, chunk,config))
			#p.daemon = True
			p.start()
			processes.append(p)
		
		# Wait for the processes to expire
		for p in processes:
			p.join()

	except KeyboardInterrupt:
			logging.info("Ctrl-c received! Sending kill to processes...")
			for p in processes:
				p.terminate()
		

