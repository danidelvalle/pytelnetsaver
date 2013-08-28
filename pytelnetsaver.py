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

# Telnet connection settings
USER = "user"
PASSWORD = "password"
PROMPT = "> "
TIMEOUT = 5

# Max wait time witout receiving data. This will
# fire sending and "\n" to avoid the session to expire due to inactivity.
MAX_WAIT_TIME = 120

# Reconnect to hosts 
RECONNECT_TIME = 300

# Max concurrent threads (-1 for no limit)
MAX_THREADS = -1

# Rotate log files when (in bytes)
MAX_FILE_SIZE = 500000

class TelnetLogSaver(threading.Thread):
	''' 
	def __init__(self, id, hostname,ip,filename):
		super(TelnetLogSaver, self).__init__()
		self.id = id 
		self.hostname = hostname
		self.ip = ip
		self.filename = filename
		self.kill_received = False
		self.daemon = True
	
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
		self.debug("checking file size")
		
		current_size = os.stat(self.filename).st_size
		self.debug("Filesize for now is %d bytes" % current_size)
		
		if current_size > MAX_FILE_SIZE:
			self.info("MAX_FILE_SIZE exceeded - rotating file")
			
			# Closing the file
			self.f.close()
			
			# Get the file number
			self.info("getting the file number")
			files = [ f for f in os.listdir(".") if (os.path.isfile(f) and f.startswith(self.hostname))]
			new_filename = "%s.%d.gz" % (self.filename, 1+len(files))
			
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
		try:
			# Store current time
			self.last_run = time.time()	
			
			# Open the file for append
			self.f = open(self.filename,"a")
			
			# Connect by telnet
			tn = telnetlib.Telnet(self.ip,23,TIMEOUT)
			#tn.set_debuglevel(1)
			
			# workarround to avoid the connection getting stuck at option negociation
			tn.set_option_negotiation_callback(self.option_negociation)
			self.info("Connecting to %s" % ( self.ip))
			e = tn.read_until("Login: ")
			tn.write(USER+"\n")
			
			e = tn.read_until("Password: ")
			tn.write(PASSWORD+"\n")
			
			e = tn.read_until(PROMPT)
			tn.write("\n")
			e = tn.read_until(PROMPT)
			self.info("connected successfully, starting infinite loop to save messages")
			
			# Connected. Start infinite loop to save messages log
			last_time_read = time.time()
			while not self.kill_received:
				
				# Wait fot data to be read
				self.debug("waiting on select for data")
				read_ready, write_ready, expt_ready = select.select([ tn.get_socket() ],[],[],MAX_WAIT_TIME)
				self.debug("select returned")

				if len(read_ready) == 1:
					readed = ""
					self.f.write("\r\n" + datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")+"\r\n")
					# Read all the data available
					while tn.sock_avail():
						e = tn.read_some()
						readed += e					
				
					self.f.write(readed)
					self.f.flush()
					self.debug("read %d characters" % (len(readed)))

				# Anti-idle protection
				if (time.time() - last_time_read) > MAX_WAIT_TIME:
					''' Avoid session auto-idle'''
					self.debug("Sending intro to avoid session timeout")
					tn.write("\n")
					e = tn.read_until(PROMPT,3*TIMEOUT)
					if e is "":
						self.error("lost connection with %s" % (self.ip))
						tn.close()
						self.f.close()
						return	
				
				''' At this point session is active because data has been received or 
				anti-idle has successed'''
				self.check_and_rotate()
				
				last_time_read = time.time()

			# gracefull closing
			self.info("finishing due to kill signal")
			tn.close()
			self.f.close()
			return

		except:
			self.error("Exception!! Finishing")
			self.f.close()
			#traceback.print_exc()
			return
	

def init_logging():

	# Start logging
	FORMAT = "%(asctime)s - %(levelname)s: %(message)s" 
	logging.basicConfig(level=logging.INFO,format=FORMAT,filename='log.log')
	# define a Handler which writes INFO messages or higher to the sys.stderr
	console = logging.StreamHandler()
	console.setLevel(logging.INFO)
	# set a format which is simpler for console use
	formatter = logging.Formatter(FORMAT)
	# tell the handler to use this format
	console.setFormatter(formatter)
	# add the handler to the root logger
	logging.getLogger('').addHandler(console)
	
if __name__ == '__main__':
	
	# init logging
	init_logging()

	# Read the host file
	file = sys.argv[1]
	mapper = lambda linea: (linea.split(";")[0],linea.split(";")[1].replace("\r\n",""))
	hosts = map(mapper, [l for l in open(file,'r')])
	random.shuffle(hosts)

	# Create the array of threads
	threads = []
	t_id = 1
	for (host,ip) in hosts:
		t = TelnetLogSaver(t_id,host,ip,host+".txt")
		threads.append(t)
		t_id+=1
	
	# Start the threads
	limit = MAX_THREADS if (MAX_THREADS != -1) else len(hosts)
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
						if elapsed > RECONNECT_TIME:
							logging.info("%d [%s] has been stopped for %d seconds. Trying to reconnect..." % (thread.id, thread.hostname,elapsed))
							t = TelnetLogSaver(thread.id,thread.hostname,thread.ip,thread.hostname+".txt")
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
#except KeyboardInterrupt:
#	print "CRTL-C: Clossing session"
#	tn.write("exit\n")
#	tn.close()
