import pjs.elementtree.ElementTree as et
import logging

from pjs.handlers.base import Handler
from pjs.utils import tostring

#TODO: do we need a handler for arbitrary binary data?

class WriteHandler(Handler):
    def handle(self, tree, msg, lastRetVal=None):
        """Attaches the lastRetVal to the message's buffer and sent it
        all out. This only works with unicode strings for now.
        """
        out = msg.outputBuffer
        
        # clear msg's buffer since we don't want it to be sent twice
        # (Dispatcher sends it after Message processing is done)
        msg.outputBuffer = u''
        
        out += prepareDataForSending(lastRetVal)
        msg.conn.send(out)

def prepareDataForSending(lastRetVal):
    """Converts lastRetVal into unicode data that's ready to be sent over
    the wire. lastRetVal can be either a single unit or a list of: text, Element
    values.
    """
    out = u''
    
    # need to test for None in case it's Element without children
    if lastRetVal is not None and not isinstance(lastRetVal, Exception):
        # process lastRetVal as a list of values to write to socket
        if not isinstance(lastRetVal, list):
            lastRetVal = [lastRetVal]
        for item in lastRetVal:
            if isinstance(item, et.Element):
                out += tostring(item)
            elif isinstance(item, str):
                out += unicode(item)
            elif isinstance(item, unicode):
                out += item
            else:
                logging.warning("prepareDataForSending: Attempting to write an object of" +\
                                " type %s to socket", type(item))
                
    return out