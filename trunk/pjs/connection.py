import pjs.async.core as asyncore
import pjs.parsers as parsers
import logging
import socket

from tlslite.integration.TLSAsyncDispatcherMixIn import TLSAsyncDispatcherMixIn

class Connection(asyncore.dispatcher_with_send):
    def __init__(self, sock, addr, server):
        asyncore.dispatcher_with_send.__init__(self, sock)
        self.sock = sock
        self.addr = addr
        self.server = server
        
        self.parser = parsers.borrow_parser(self)
        
        # any sort of per-connection data. can be accessed by handlers.
        # right now:
        # 'stream' : {
        #              'in-stream' : True/False (False before <stream> sent and after </stream>),
        #              'type' : 'client'/'server' (ie. c2s/s2s),
        #              'id' : streamid (as str)
        #            },
        # 'sasl' : {
        #            'mech' : 'PLAIN' / 'DIGEST-MD5',
        #            'mechObj' : <reference to one of SASL mech objects>
        #            'complete' : True/False
        #          },
        # 'tls' : {
        #           'complete' : True/False
        #         }
        # 'user' : {
        #            'jid' : str (server-assigned jid),
        #            'resource' : str (server-assigned resource),
        #            'in-session' : True/False (True if <session> sent/accepted)
        #          },
        #
        self.data = {}
        
        logging.info("New connection accepted from %s", self.addr)
        
    def handle_expt(self):
        logging.warning("Socket exception occured for %s", self.addr) 
    
    def handle_close(self):
        try:
            self.parser.close()
        except:
            pass
        self.parser.resetStream()
        self.close()
        
    def handle_read(self):
        data = self.recv(4096)
        self.parser.feed(data)

class LocalTriggerConnection(asyncore.dispatcher_with_send):
    """This creates a local connection back to our server.
    
    This should never be used to send any real data. This is used by the
    threadpool code to trigger a wake-up to asyncore, which could go to sleep
    for as long as 30 seconds when there is no data on the wire, which is a
    problem when we have threads finishing work in the pools. The callbacks
    need to be executed from the main thread with threadpool.poll() in order
    to proceed with message handling, but this can't happen when asyncore is
    asleep. So, each WorkThread sends a single space on this connection, which
    causes asyncore to wake up and process the event, thereby triggering
    function watching (which usually includes a threadpool.poll() call).
    """
    def __init__(self, ip, port):
        asyncore.dispatcher_with_send.__init__(self)
        
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect((ip, port))
        
        logging.info("New local trigger connection created")
        
    def handle_expt(self):
        logging.warning("Socket exception occured for %s on local trigger socket", self.addr)
    
    def handle_close(self):
        self.close()
        
    def handle_read(self): pass
    def handle_connect(self): pass