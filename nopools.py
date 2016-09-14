from __future__ import print_function
import sys
import os
import json
import socket
import urllib
import urllib.request
import hashlib
import random
import traceback

import uuid
import time
import subprocess
import os.path
import multiprocessing
import multiprocessing.pool
from multiprocessing import Process, TimeoutError, Manager
from threading import Timer

#list of processes, how many processes to put into the pool
#and how many total jobs to run, respectively
LIST_PROCESSES = []
MAX_PROCESSES = 20
SUB_PROCESSES = 50
PHANTOMJS_TIMEOUT = 300 
TRACEROUTE_PORT = 80
TRACEROUTE_MAX_PARALLEL_HOP = 10
TRACEROUTE_MAX_HOP = 21
TRACEROUTE_TIMEOUT = 3
socket.setdefaulttimeout(10)

manager = Manager()
#lock = manager.Lock()
#traceroute_lock = manager.Lock()
#traceroute_dict = manager.dict()

#wrapper that allows  pool within a pool
class NonDaemonicPool(multiprocessing.pool.Pool):

    class NoDaemonProcess(Process):

        def _get_daemon(self):
            return False

        def _set_daemon(self, value):
            pass

        daemon = property(_get_daemon, _set_daemon)

    Process = NoDaemonProcess

def custom_print(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.stderr.flush()

#closes connection to url
def handler(fh):
    try:
        fh.close()
    except:
        custom_print("Error in handler")

#retrieved ip from a url passed in
def get_ip(url):
    try:
        uri = url[8:] if url.lower().startswith('https://') else url[7:]
        domain = uri.split("/")[0]
        domain = domain.split(":",1)[0]
        ip_address = socket.gethostbyname(domain)
    except:
        ip_address = None
    return ip_address

#return traceroute for a certain ip(list format)
def add_traceroute(ip_address):
    traceroute_ips_and_countries = []
    try:
        if os.path.isfile('traceroutennp_lists/%s' % ip_address):
            traceroute_ips_and_countries.append('alreadyfoundtraceroute')
            return ({'traceroute': traceroute_ips_and_countries})
        else:
            path = 'traceroutennp_lists/%s' % ip_address
            fd = open(path, 'w')
            fd.close()
    except Exception as e:
        custom_print('problem with traceroute lock ', e, traceback.format_exc())
        return({'traceroute':'error'})

    try:
        proc = subprocess.Popen(["traceroute", "-q", "1", ip_address],
             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        traceroute_stdout, traceroute_stderr = proc.communicate()


        if proc.returncode is not None and proc.returncode != 0:
            return({'traceroute':'error'})

    except Exception as e:
        custom_print(e, traceback.format_exc())
        return ({'traceroute': 'error'})

    try:
        traceroute_list = traceroute_stdout.decode('utf-8').split('\n')
    except Exception as e:
        return {'traceroute': traceroute_ips_and_countries}

    for line in traceroute_list:
        if line != '':
            traceroute_line = line.split()

            if len(traceroute_line) > 2:
                traceroute_ip = traceroute_line[2].replace('(', '')
                traceroute_ip = traceroute_ip.replace(')', '')
            else:
                traceroute_ip = '*'

            traceroute_ips_and_countries.append((traceroute_line[0],traceroute_ip,traceroute_line[1]))

    return ({'traceroute': traceroute_ips_and_countries})

#adds fetch fo the resource
def add_fetch(data):
    USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_3) AppleWebKit/601.4.4 (KHTML, like Gecko) Version/9.0.3 Safari/601.4.4'
    ACCEPT = '*/*'
    #header to be used for the fetch
    hdr = {'User-Agent': USER_AGENT,
        'Accept': ACCEPT,}

    #extracts the uri
    if data.startswith('https://'):
        uri = data[8:]
    elif data.startswith('http://'):
        uri = data[7:]
    else:
        uri = data

    response = {}
    response["orig_https"] = data.lower().startswith("https://")
    #tries a fetch for the following four combination and
    #keeps track of errors

    for t in ("http", "https"):
        url = "%s://%s" % (t, uri)
        try:
            req = urllib.request.Request(url, None, hdr)
            site = urllib.request.urlopen(req, timeout=10, cafile="./tls-ca-bundle.pem")
            timer = Timer(15.0, handler, [site])
            timer.start()
            hd = site.read()
            timer.cancel()
            response["fetch_%s_sha1" % t] = hashlib.sha1(hd).hexdigest()
            response["fetch_%s_status" % t] = "ok"
        except ConnectionResetError as e:
            response["fetch_%s_status" % t] = "error"
            response["fetch_%s_status_reason" % t] = 'Connection Reset by peer'
            response["fetch_%s_error_name" % t] = e.__class__.__name__
        except Exception as e:
            try:
                response["fetch_%s_status" % t] = "error"
                response["fetch_%s_status_reason" % t] = str(e.reason)
                if str(e.reason) == 'HTTPError':
                    response["fetch_%s_status_code" % t] = str(e.code)
                response["fetch_%s_error_name" % t] = e.__class__.__name__
            except AttributeError as ex:
                response["fetch_%s_status" % t] = "error"
                response["fetch_%s_status_reason" % t] = str(ex)

                if 'CertificateError' in str(ex):
                    response["fetch_%s_status_reason" % t] = 'CertificateError'

                if 'hostname' in str(ex):
                    response["fetch_%s_error_name" % t] = 'SNI mismatch'
                elif 'timed out' in str(ex):
                    response["fetch_%s_error_name" % t] = 'fetch timeout'
                elif 'has no attribute' in str(ex):
                    response["fetch_%s_error_name" % t] = 'redirect timeout'
                elif 'BadStatusLine' in str(ex):
                    response["fetch_%s_error_name" % t] = 'http bad error code'
                elif 'IncompleteRead' in str(ex):
                    response["fetch_%s_error_name" % t] = 'Incomplete Read'
                elif 'InvalidURL' in str(ex):
                    response["fetch_%s_error_name" % t] = 'Invalid URL'
                else:
                    response["fetch_%s_error_name" % t] = str(ex)
                    custom_print('custom error', ex, traceback.format_exc())
            except Exception as ex:
                response["fetch_%s_status" % t] = "error"
                response["fetch_%s_status_reason" % t] = str(ex)
                response["fetch_%s_error_name" % t] = ex.__class__.__name__
                raise
    return (response)

#kicks off the traceroute, ip, and fetch
#afterwards, combines results into one dict
#and returns that to be reinjected into python
def add_traceroute_and_fetch(data):
    #only one process will run this entire function
    try:
        ip = {}
        ip['ip_address'] = get_ip(data)
        if ip['ip_address'] is not None:
            traceroute = add_traceroute(ip['ip_address'])
        else:
            traceroute = {'traceroute': ''}
        fetch = add_fetch(data)
        combined = traceroute
        combined.update(ip)
        combined.update(fetch)
    except Exception as e:
        custom_print('error in add traceroute and fetch', e, traceback.format_exc())
        return ({'traceroute':'error', 'ip_address':'error',
            'fetch_http_status': 'error', 'fetch_https_status': 'error'})
    return (combined)

#Website object
class Website(object):

    def __init__(self, domain_tuple):
        self.rank = int(domain_tuple[0])
        self.domain = domain_tuple[1]
        self.http_url = 'http://' + self.domain
        self.https_url = 'https://' + self.domain
        self.stdout_data = None
        self.stderr_data = None
        self.error = None
        self.error_reason = None

    #classmethod that instantiates a new object and runs process_phantomjs and returns
    #the output. This plays nicely with python multiprocessing
    @classmethod
    def run_all(cls, *args, **kwargs):
        return(cls(*args, **kwargs).process_phantomjs())

    #parses through and returns a label if phantomjs runs into a problem
    def parse_error(self):
        try:
            substring = b"PhantomJS has crashed"
            if substring in self.stderr_data:
               self.error_reason = 'phantomjs bug report'
            else:
                #with lock:
                #    custom_print(self.stdout_data)
                #    custom_print(self.stderr_data)
                #    sys.stdout.flush()
                self.error_reason = 'UNKNOWN BUG'
        except Exception as e:
            custom_print('error in parse error', self.domain, e, traceback.format_exc())
            raise
    #check if the phantomjs crashed but still produced output
    #ex. b'{"domain":"http://www.pakistan360degrees.com","error_received":"did_not_load","error_message":"Operation canceled"}\n'
    def check_if_canceled(self):
        try:
            js_output = self.stdout_data
            json_output = json.loads(js_output)
            if 'error_received' in json_output:
                if json_output['error_received']  == 'did_not_load':
                    self.error_reason = 'did_not_load'
                    self.error = 'internal phantom error'
                    phantomjs_output = {
                        "data": json_output,
                        "domain": self.domain,
                        "rank": self.rank,
                        "error_reason": self.error_reason,
                        "error_output": self.error,
                    }
                else:
                    self.error_reason = 'unclear'
                    self.error = 'internal phantom error'
                    phantomjs_output = {
                        "data": json_output,
                        "domain": self.domain,
                        "rank": self.rank,
                        "error_reason": self.error_reason,
                        "error_output": self.error,
                    }
                return ([True, phantomjs_output])
            else:
                #no problem here
                return ([False, self.stdout_data])
        except Exception as e:
            custom_print('error in check_if_canceled', self.domain, e, traceback.format_exc())
            raise
    
    def phantomjs_killed(self):
        json_output = str(None)
        self.error_reason = 'phantomjs timed out'
        self.error = 'no error output'

        phantomjs_output = {
            "data": json_output,
            "domain": self.domain,
            "rank": self.rank,
            "error_reason": self.error_reason,
            "error_output": self.error,
        }
        return (phantomjs_output)

    def is_valid_json(self):
        try:
            #merely decoding makes the dict look weird, so you have to load it afterwards
            js_output = self.stdout_data
            json_output = json.loads(js_output)
            return True
        except Exception as e:
            #custom_print('error in get_json', self.domain, e, traceback.format_exc())
            self.error = 'undecodable json'
            self.error_reason = 'phantomjs json undecodable'
            return False

    #takes input and gives appropriate, formated json to custom_print
    def get_json(self):
        if self.error is None:
            try:
                #merely decoding makes the dict look weird, so you have to load it afterwards
                js_output = self.stdout_data
                json_output = json.loads(js_output)
                if 'error_received' in json_output:
                    if json_output['error_received'] == 'did_not_load':
                        self.error = 'phantomjs internal error'
                        self.error_reason = 'did_not_load'
            except Exception as e:
                custom_print('error in get_json', self.domain, e, traceback.format_exc())
                raise
        else:
            if self.error == 'undecodable json':
                json_output = self.stdout_data
            else:
                json_output = str(None)

        phantomjs_output = {
            "data": json_output,
            "domain": self.domain,
            "rank": self.rank,
            "error_reason": str(self.error_reason),
            "error_output": str(self.error),
        }
        return (phantomjs_output)

    #goes through and processes resources for the website
    #beginning of post process
    def post_process_resources(self, phantomjs_output):

        starttime = int(time.time())
        if self.error:
            return (phantomjs_output)

        custom_print ("Domain: " + self.domain + " starttime: " + str(starttime))

        #put error handling here for faulty pahtnomjs
        def traverse(doc, to_process):
            try:
                to_process.append(doc["data"])
                for child in doc.get("children", []):
                    traverse(child, to_process)
            except Exception as e:
                custom_print('problem in traverse', self.domain, e, traceback.format_exc())
                raise

        def reinject(doc, results):
            try:
                doc.update(results.pop(0))
                for child in doc.get("children", []):
                    reinject(child, results)
            except Exception as e:
                custom_print('problem in reinject', self.domain, e, traceback.format_exc())
                raise

        unrolled = []
        results = []
        try:

            traverse(phantomjs_output['data']['_root'], unrolled)

            sub_pool = multiprocessing.Pool(processes=SUB_PROCESSES)
            results = sub_pool.map(add_traceroute_and_fetch, unrolled)

        except Exception as e:
            custom_print('problem with calling traverse', self.domain, e, traceback.format_exc())
            raise

        post_processed = phantomjs_output

        try:
            reinject(post_processed['data']['_root'], results)
            sub_pool.terminate()
        except Exception as e:
            custom_print('problem with reinject', self.domain, traceback.format_exc())
            raise

        endtime = int(time.time())
        custom_print ("Domain: " + self.domain + "   endtime: " + str(endtime) + " duration: " + str(endtime - starttime))
        return(post_processed)

    #sees if phantomjs failed (and if we need to do www)
    def check_phantomjs(self, phantomjs_output):
        try:
            js_output = phantomjs_output
            json_output = json.loads(js_output)
            if "error_received" in json_output:
                if json_output["error_received"] == "did_not_load":
                    return True
                else:
                    return False
            else:
                return False
        except Exception as e:
            custom_print('error in check phantom', e, traceback.format_exc())
            raise

    #runs phantomjs for this particular website
    def process_phantomjs(self):
        timer = 0
        kill = 0
        starttime = int(time.time())

        custom_print("PROCESS: Domain: " + self.domain + " start time: " + str(starttime))
        temp_filename = str(uuid.uuid4()) + ".log"

        try:
            count = 0
            rc = 98
            while(rc == 98):
                custom_print(self.http_url)
                port = str(random.randint(10000,60000))
                proc = subprocess.Popen(["node", "../js/network.js", "../src/out/Headless/headless_shell", self.http_url, temp_filename, port],
                #proc = subprocess.Popen(["./phantomjs", "--disk-cache=false",
                    #"--ssl-protocol=any", "tree.js", self.http_url],
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        
                #timer that will kill phantomjs if it never times out after 5 minutes
                timer = Timer(PHANTOMJS_TIMEOUT, lambda p: p.kill(), [proc])
                timer.start()
                kill = 1

                #blocks until the process is finished
                self.stdout_data, self.stderr_data = proc.communicate()
                rc = proc.returncode            
            custom_print(self.http_url + " returned " + str(rc)) 
            
            if proc.returncode is not None and proc.returncode == -6:
                raise RuntimeError('nodejs heap overflow error')

            #We want to run www version of the site to test
            with open(temp_filename) as f:
                self.stdout_data = f.read()
            os.remove(temp_filename)
            
            if proc.returncode is not None and proc.returncode == 7 and not\
                self.domain.startswith('www.'):
                return([self.rank, self.domain])

            #if proc exits correctly, everything ok
            if proc.returncode is not None and proc.returncode == 0 and not\
                self.domain.startswith('www.'):
                #check if phantomjs died internally
                is_valid_js = self.is_valid_json()
                if is_valid_js:
                    died = self.check_phantomjs(self.stdout_data)
                    if died:
                        return([self.rank, self.domain])
                phantomjs_output = self.get_json()
            #if proc exits under error code (proc did not finish correctly), try to figure out error
            elif proc.returncode is not None and proc.returncode == 0:
                #check if operation is canceled
                #If canceled, modify_operation canceled
                canceled = self.check_if_canceled()
                if not canceled[0]:
                    phantomjs_output = self.get_json()
                else:
                    phantomjs_output = canceled[1]
            elif proc.returncode is not None and proc.returncode == -9:
                phantomjs_output = self.phantomjs_killed()
            elif proc.returncode is not None:
                self.parse_error()
                self.error = self.stderr_data.decode('utf-8')
                phantomjs_output = self.get_json()
            #this means the process is still running and should NEVER happen because of .communicate
            #if this happens something is severly wrong with the multiprocessing library
            #for now i still output a json object but with a message saying that the returncode is None
            else:
                self.error_reason = 'proc.returncode is None'
                self.error = 'proc.returncode is None'
                phantomjs_output = self.get_json()
        #catches unforseen errors
        except Exception as e:
            #set self.erro and self.error_reason
            self.error = 'unknown error'
            self.error_reason = 'unknown error'
        finally:
            if kill == 1:
                timer.cancel()
        try:
            processed_output = self.post_process_resources(phantomjs_output)
        except Exception as e:
            #set self.erro and self.error_reason
            processed_output = {
                "data": None,
                "domain": self.domain,
                "rank": self.rank,
                "error_reason": 'unknown',
                "error_output": 'unknown',
            }

        endtime = int(time.time())

        custom_print("PROCESS: Domain: " + self.domain + " end time: " + str(endtime) + " duration: " + str(endtime - starttime))
        return (processed_output)

#this function exists merely to start the instantiation of the new website object
#and kick off all the processes associated with a website
def process_website(*args, **kwargs):
    return Website.run_all(*args, **kwargs)

#reads in alexa file (sys.argv[1]) and outputs tuple (rank, domain)
def grab_alexa_domains(input_filename):
    domains = []
    with open(input_filename, 'r') as input_file:
        for line in input_file:
            try:
                line_components = line.split(',')
                domains.append((line_components[0], line_components[1].rstrip()))
            except Exception as e:
                custom_print('Problem with alexa input file, please check that the format of the file is rank,domain')
                raise
                #raise e

    return (domains)

#reads in alexa file(sys.argv[1]) and takes in random N of the file
def grab_random_alexa_domains(input_filename, output_filename):
    domains = []
    random_domains = []
    random_numbers = []
    limit = 1000000
    limit_random = 100
    with open(input_filename, 'r') as input_file:
        for line in input_file:
            try:
                line_components = line.split(',')
                domains.append((line_components[0], line_components[1].rstrip()))
            except Exception as e:
                custom_print('Problem with alexa input file, please check that the format of the file is rank,domain')
                raise
                #raise e

    for num in range(0, limit_random):
        next_number = random.randint(0, limit)
        while next_number in random_numbers:
            next_number = random.randint(0, limit)
        random_numbers.append(next_number)

    random_domains = [domains[x] for x in random_numbers]
    with open(output_filename, 'w') as output_file:
        for item in random_domains:
            line = str(item[0]) +  "," + str(item[1]) + "\n"
            output_file.write(line)

    return (random_domains)

if __name__ == "__main__":

    try:
        beginning_proc = subprocess.check_call(['rm', '-rf', 'traceroutennp_lists'])
    except Exception as e:
        custom_print('Problem with removing traceroutennp_lists_dir, cannot continue')
        raise

    try:
        beginning_proc = subprocess.check_call(['mkdir', 'traceroutennp_lists'])
    except Exception as e:
        custom_print('Problem with makign traceroutennp_lists dir')
        raise

    pool = NonDaemonicPool(processes=MAX_PROCESSES)
    try:

        if len(sys.argv) < 2:
            custom_print('need an inputfile name that matches Alexa format')
            custom_print('python3 pluto.py input_file 1 2')
            raise

        else:
            alexa_input_filename = sys.argv[1]
            beginning_range = int(sys.argv[2])
            end_range = int(sys.argv[3])

        #process alexa file as tuples of (rank, domain)
        #alexa_domains = grab_random_alexa_domains(alexa_input_filename, alexa_output_filename)
        alexa_domains = grab_alexa_domains(alexa_input_filename)
        i = 0
        domains_to_process = []
        for i in range(beginning_range-1, end_range):
            if i < len(alexa_domains):
                domains_to_process.append(alexa_domains[i])
            else:
                break
        total_runs = len(domains_to_process)

        args = [
        ]

        multiple_results = [pool.apply_async(process_website,(domains_to_process[i],)) for i in range(total_runs)]
        new_num = total_runs
        for res in multiple_results:
            while 1:
                try:
                    result = res.get(timeout=400)
                    #makes sure that the .communicate finishes..should NEVER be None
                    if result is not None and isinstance(result, list):
                        new_domain = result
                        new_domain[1] = 'www.'+new_domain[1]
                        multiple_results.append(pool.apply_async(process_website,(new_domain,)))
                    elif result is not None:
                        print(json.dumps(result))
                        sys.stdout.flush()
                    else:
                        custom_print('Something is REALLY wrong with process_phantomjs')
                    break
                #should never execute with current code because timeout is not set
                except TimeoutError:
                    custom_print('timeout')
                    #time.sleep(5)
                    #pass
                    break
                except Exception as e:
                    custom_print('Something wrong in multiple_results loop', e, traceback.format_exc())
                    break
    except Exception as e:
            custom_print(e, traceback.format_exc())
            exit(1)

