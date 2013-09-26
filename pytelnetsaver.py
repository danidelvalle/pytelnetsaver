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
from pprint import pprint

class TelnetLogSaver(threading.Thread):
	''' Thread that connects to a host by telnet and starts to save 
	to a file all messages readed.
	'''
	
	def __init__(self, id, hostname,ip,filename, options):
		super(TelnetLogSaver, self).__init__()
		self.id = id 
		self.hostname = hostname
		self.ip = ip
		self.filename = filename
		self.kill_received = False
		self.daemon = True
		
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
		
		self.exec_initial_commands = False
		if "initial_commands" in options["telnet"]:
			self.exec_initial_commands = True
			self.initial_commands =  options["telnet"]["initial_commands"]
			self.initial_expects =  options["telnet"]["initial_expects"] 
		
		self.exec_recurrent_commands = False
		if "recurrent_commands" in options["telnet"]:
			 self.exec_recurrent_commands = True
			 self.recurrent_commands =  options["telnet"]["recurrent_commands"]
			 self.recurrent_expects =  options["telnet"]["recurrent_expects"]
			 self.recurrent_period =  options["telnet"]["recurrent_period"]
			 self.last_exec_recurrent = 0
		
		self.max_file_size = options["output"]["max_file_size"]
	
	def info(self, msg):
		logging.info("%d [%s] - %s" % (self.id,self.hostname,msg))
	
	def debug(self, msg):
		logging.debug("%d [%s] - %s" % (self.id,self.hostname,msg))
	
	def error(self, msg):
		logging.error("%d [%s] - %s" % (self.id,self.hostname,msg))
		
	def option_negociation(self, socket, command, option):
		logging.debug("dummy option_negociation")
		
	def check_recurrent_commands(self,tn):
		if self.exec_recurrent_commands:
			self.debug("check_recurrent_commands")
			elapsed = time.time() - self.last_exec_recurrent
			if elapsed > self.recurrent_period:
				self.info("Recurrent Exec Period reached: executing commands")

				for index in range(0,len(self.recurrent_commands)):
					command = self.recurrent_commands[index]
					expect = self.recurrent_expects[index]
					self.debug("Sending recurrent command %d: %s" %(index,command))
					tn.write(command+"\n")
					self.debug("Waiting for recurrent expect %d: %s" %(index,expect))
					response = tn.read_until(expect)
					self.f.write(response)
				
				self.last_exec_recurrent = time.time()
				
	
	def check_and_rotate(self):
		''' Check the file size and rotate if necessary '''
		
		self.debug("checking file size")
		
		current_size = os.stat(self.filename).st_size
		self.debug("Filesize for now is %d bytes" % current_size)
		
		if current_size > self.max_file_size:
			self.info("'output.max_file_size' exceeded - rotating file")
			
			# Closing the file
			self.f.close()
			
			# Get the file number
			self.info("getting the file number")
			path = os.path.dirname(self.filename)
			basename = os.path.basename(self.filename)
			files = [ f for f in os.listdir(path) if (os.path.join(path,f) and f.startswith(basename))]
			new_filename = os.path.join(path, "%s.%d.gz" % (basename, 1+len(files)))
			
			logging.info("creating new file '%s'" % new_filename)
			
			# Compress the file
			self.info("moving and compressing the file")
			f_in = open(self.filename, 'rb')
			f_out = gzip.open(new_filename, 'wb')
			f_out.writelines(f_in)
			f_out.close()
			f_in.close()
			
			# reopen the file (override)
			self.info("reopening the file (overriding)")
			self.f = open(self.filename, "w")
			
	def run(self):
		''' Implements thread logic. It runs an infinite loop until an external kill 
		signal is received (from the main thread) and waits for data using 'select'.
		'''	
		
		try:
			# Store current time
			self.last_run = time.time()	
			
			# Open the file for append
			self.f = open(self.filename,"a")
			
			# Connect by telnet
			tn = telnetlib.Telnet(self.ip,23,self.timeout)
			
			# Enables telnet debugging
			if self.telnet_debug == 1:
				tn.set_debuglevel(1)
			
			# workarround to avoid the connection getting stuck at option negociation
			tn.set_option_negotiation_callback(self.option_negociation)
			self.info("Connecting to %s" % ( self.ip))
			
			# first prompt
			if self.first_prompt is (not None and not ""):
				self.debug("waiting for first prompt '%s'" % self.first_prompt)
				e = tn.read_until(self.first_prompt)	
			
			# Initial newLine
			if self.initial_newline == 1:
				self.debug("sending initial newline character")
				tn.write("a\n")
			
			self.debug("waiting for '%s'" % self.expected_user_string)
			e = tn.read_until(self.expected_user_string)
			tn.write(self.user+"\n")
			
			self.debug("waiting for '%s'" % self.expected_password_string)
			e = tn.read_until(self.expected_password_string)
			tn.write(self.password+"\n")
			
			e = tn.read_until(self.prompt)
			tn.write("\n")
			e = tn.read_until(self.prompt)
			
			# Initial commands
			if self.exec_initial_commands:
			  self.info("Sending initial commands")
			  for index in range(0,len(self.initial_commands)):
				command = self.initial_commands[index]
				expect = self.initial_expects[index]
				self.debug("Sending initial command %d: %s" %(index,command))
				tn.write(command+"\n")
				self.debug("Waiting for initial expect %d: %s" %(index,expect))
				tn.read_until(expect)
			
			self.info("connected successfully, starting infinite loop to save messages")
			
			# Connected. Start infinite loop to save messages log
			last_time_read = time.time()
			while not self.kill_received:
				
				# Wait fot data to be read using 'select'
				self.debug("waiting on select for data")
				read_ready, write_ready, expt_ready = select.select([ tn.get_socket() ],[],[],self.max_wait_time)
				self.debug("select returned")

				if len(read_ready) == 1:
					read = ""
					self.f.write("\r\n" + datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")+"\r\n")
					# Read all the data available
					while tn.sock_avail():
						e = tn.read_some()
						read += e					
					
					self.debug("About to write %d characters to file" % len(read))
					self.f.write(read)
					self.debug("About to flushing file")
					self.f.flush()
					self.debug("read %d characters" % (len(read)))
				
				else:
					self.debug("Select returned by no sockets to read from")

				# Anti-idle protection
				if (time.time() - last_time_read) > self.max_wait_time:
					''' Avoid session auto-idle'''
					self.debug("Sending intro to avoid session timeout")
					tn.write("\n")
					e = tn.read_until(self.prompt,3*self.timeout)
					if e is "":
						self.error("lost connection with %s" % (self.ip))
						tn.close()
						self.f.close()
						return	
				
				''' At this point session is active because data has been received or 
				anti-idle has successed. Check if is necessary to rotate and compress the 
				log'''
				self.check_and_rotate()
				
				''' Recurrent commands '''
				self.check_recurrent_commands(tn)
				
				# Update the last iteration time 
				last_time_read = time.time()

			# gracefull closing
			self.info("finishing due to kill signal, sending 'exit'")
			tn.write("exit\n")	
			tn.close()
			self.f.close()
			return

		except Exception as e:
			self.error(e)
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
			"max_threads": -1,
			"initial_newline": 0,
			"expected_user_string": "user:",
			"expected_password_string": "password:",
			"max_file_size": 120,
			"first_prompt": "",
			"telnet_debug": 0,
			"initial_expects": "",
			"initial_commands": "",
			"recurrent_expects": "",
			"recurrent_commands": "",
			"recurrent_period": 0,
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
	configuration["telnet"]["max_threads"] = config.getint("telnet","max_threads")
	configuration["telnet"]["initial_newline"] = config.getint("telnet","initial_newline")
	configuration["telnet"]["telnet_debug"] = config.getint("telnet","telnet_debug")
	configuration["telnet"]["expected_user_string"] = config.get("telnet","expected_user_string").strip('"')
	configuration["telnet"]["expected_password_string"] = config.get("telnet","expected_password_string").strip('"')
	
	''' Initial commands and expects - custom list parsing. Assumed '|' separator. Both params
	must have the same number of members, otherwise this feature is ignored.
	'''
	initial_commands = config.get("telnet","initial_commands")
	initial_expects = config.get("telnet","initial_expects")
	
	if 	initial_commands is not None and len(initial_commands) > 2 and \
		initial_expects is not None and len(initial_expects) > 2 and \
		len(initial_commands.strip('"').split('|')) == len(initial_expects.strip('"').split('|')):
	
		configuration["telnet"]["initial_commands"] = initial_commands.strip('"').split('|')
		configuration["telnet"]["initial_expects"] = initial_expects.strip('"').split('|')
	
	''' Initial commands and expects - custom list parsing. Assumed '|' separator. Both params
	must have the same number of members, otherwise this feature is ignored.
	'''
	recurrent_commands = config.get("telnet","recurrent_commands")
	recurrent_expects = config.get("telnet","recurrent_expects")
	configuration["telnet"]["recurrent_period"] = config.getint("telnet","recurrent_period")
	
	if 	recurrent_commands is not None and len(recurrent_commands) > 2 and \
		recurrent_expects is not None and len(recurrent_expects) > 2 and \
		len(recurrent_commands.strip('"').split('|')) == len(recurrent_expects.strip('"').split('|')):
	
		configuration["telnet"]["recurrent_commands"] = recurrent_commands.strip('"').split('|')
		configuration["telnet"]["recurrent_expects"] = recurrent_expects.strip('"').split('|')
	
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
	parser.add_option("-v", "--verbose", dest="verbose", action="store_true")
	
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
		
	pprint(config)
	#exit(0)
	
	# init logging
	level = logging.DEBUG if options.verbose else logging.INFO
	init_logging(config["logging"]["log_file"], level)
	
	# Read the host file
	file = options.hosts_file
	mapper = lambda line: (line.split(";")[0],line.split(";")[1].replace("\r\n",""))
	hosts = map(mapper, [l for l in open(file,'r')])
	random.shuffle(hosts)

	# Create the array of threads
	threads = []
	t_id = 1
	for (host,ip) in hosts:
		host_log_file = "%s/%s.txt" % (config["output"]["output_dir"],host)
		t = TelnetLogSaver(t_id,host,ip,host_log_file,config)
		threads.append(t)
		t_id+=1
	
	# Start the threads
	if config["telnet"]["max_threads"] == -1:
		limit = len(hosts)
	else:
		limit = min(len(hosts),config["telnet"]["max_threads"])

	effective_threads = threads[:limit]
	
	for i in range(0,limit):
		effective_threads[i].start()
	
	# Wait and auto-remove died threads
	it=0
	while len(effective_threads) > 0:
		try:
			for thread in effective_threads:	
				# Log each 60sec aprox how many threads are running
				it += 1
				if it%120 == 0:
					logging.info("%d threads running" % len(effective_threads))
				
				if thread.isAlive():
					logging.debug("%d is running - joining" % thread.id)
					thread.join(1)
				else:
					logging.debug("%d - %s: is not running" % (thread.id, thread.hostname))
					effective_threads.remove(thread)
					
					# Try lo restart the thread
					if not thread.kill_received:
						# Check last restart attempt
						elapsed = time.time() - thread.last_run
						if elapsed > config["telnet"]["reconnect_interval"]:
							logging.info("%d [%s] has been stopped for %d seconds. Trying to reconnect..." % (thread.id, thread.hostname,elapsed))
							t = TelnetLogSaver(thread.id,thread.hostname,thread.ip,thread.filename,config)
							effective_threads.append(t)
							t.start()
						
		except KeyboardInterrupt:
			logging.info("Ctrl-c received! Sending kill to threads...")
			for t in effective_threads:
				t.kill_received = True
		except:
			logging.error("Main thread exception")
			traceback.print_exc()
	
	logging.info("Bye bye !!")
