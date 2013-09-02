# pyTelnetSaver

Easy telnet hundred of elements and save their message logs.

Usage:

`python pytelnetsaver.py -c example_config.cfg -f example_hosts.csv`

The script is designed to telnet as many same-type-devices as possible, for instance, cablemodems or CPEs (costumer premises equipment). 

As these kind of application is limited by network latencies, using threads performs better as requires less resources comparing with procesess. 

So, the script does the following:

* Read the config file, where some needed options are stored (telnet settings, threading limits, logging, etc.)
* Opens one thread for each host. Each thread mantains open the telnet session with an anti-idle keepalive feature, and stores to a local file all messages sent by remote peer. Each threads blocks using `select.select()` until some data is available to be read.
* If some connection is lost (or was never started), the script tries to automatically reconnect.

Depending on the machine, a single instance of the script has been used without issues for 300+ devices. For a higher number, it may crash with an `segmentation fault`.


