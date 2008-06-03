import pjs.handlers.base
import logging

from pjs.conf.phases import corePhases, stanzaPhases
from pjs.conf.handlers import handlers as h

class Message:
    def __init__(self, tree, conn, handlers, errorHandlers, currentPhase=None):
        self.tree = tree
        self.conn = conn
        self.handlers = handlers or []
        self.errorHandlers = errorHandlers or []
        self.currentPhase = currentPhase
        
        # Signals to process() to stop running handlers. Handlers can signal
        # this directly.
        self.stopChain = False
        
        # Currently executing pair of (handler, errorHandler)
        # This is saved in order to properly handle exceptions thrown in
        # handlers.
        self._runningHandlers = (None, None)
        # Indicates whether we're executing the last handler in a pair. This is
        # necessary, because we need to decide when to clear
        # self.runningHandlers to proceed to the next pair.
        # Setting this to True is basically skipping the remaining handler in
        # pair and proceeding to the next set.
        self.lastInPair = False
        
        # Return value from the last handler. Could be an Exception object.
        self._lastRetVal = None
        
        # Indicates whether the last handler threw and exception
        self._gotException = False
        
        # Called by this object to notify the waiting handler that it can
        # continue.
        self._handlerResumeFunc = None
        
        # For handlers to append to. the write handler will process this.
        # Use addTextOutput() instead of appending to this directly.
        self.outputBuffer = u''
        
    def addTextOutput(self, data):
        """Handlers can use this to buffer unicode text for output.
        This will be sent by the write handler.
        """
        self.outputBuffer += unicode(data)
    
    def process(self):
        """Runs the handlers"""
        
        # If we don't have error handlers, that's ok, but if we don't have
        # handlers, then we quit. Handlers are popped from the handlers list
        # instead of iterated on because we expect handlers to be able to add
        # other handlers onto the list.
        while 1:
            if self.stopChain:
                break
            
            if self._runningHandlers != (None, None):
                handler, errorHandler = self._runningHandlers
            else:
                try:
                    handler = self.handlers.pop(0)
                except IndexError:
                    break
                
                try:
                    errorHandler = self.errorHandlers.pop(0)
                except IndexError:
                    errorHandler = None
                
                self._runningHandlers = (handler, errorHandler)
                self.lastInPair = False
                
            shouldReturn = self._execLink()
            
            if shouldReturn:
                return
                
    def resume(self):
        """Resumes the execution of handlers. This is the callback for when
        the thread is done executing. It gets called by the Connection.
        """
        if callable(self._handlerResumeFunc):
            self._lastRetVal = self._handlerResumeFunc()
        if isinstance(self._lastRetVal, Exception):
            self._gotException = True
        else:
            self._gotException = False
            self.lastInPair = True
        self._updateRunningHandlers()
        self.process()
            
    def _updateRunningHandlers(self):
        """Resets running handlers to None if executing the last handler"""
        if self.lastInPair:
            self._runningHandlers = (None, None)
    
    def _execHandler(self, handler):
        """Run a handler in-process"""
        try:
            self._lastRetVal = handler.handle(self.tree, self, self._lastRetVal)
            self._gotException = False
        except Exception, e:
            self._gotException = True
            self._lastRetVal = e
    
    def _execThreadedHandler(self, handler):
        """Run a handler out of process with a callback to resume"""
        checkFunc, initFunc = handler.handle(self.tree, self, self._lastRetVal)
        self._handlerResumeFunc = handler.resume
        self.conn.watch_function(checkFunc, self.resume, initFunc)
    
    def _execLink(self):
        """Execute a single link in the chain of handlers"""
        
        handler, errorHandler = self._runningHandlers
        
        if self._gotException:
            self.lastInPair = True
            if errorHandler is not None:
                # executing the error handler
                if isinstance(errorHandler, pjs.handlers.base.Handler):
                    self._execHandler(errorHandler)
                elif isinstance(errorHandler, pjs.handlers.base.ThreadedHandler):
                    self._execThreadedHandler(errorHandler)
                    return True
                else:
                    logging.warning("Unknown error handler type (%s) for %s",
                                    type(errorHandler), errorHandler)
            else:
                logging.warning("No error handler assigned for %s", handler)
                
            self._updateRunningHandlers()
        else:
            # executing the normal handler
            self.lastInPair = False
            if isinstance(handler, pjs.handlers.base.Handler):
                self._execHandler(handler)
                if not self._gotException: # if no exception, we're done with this pair
                    self.lastInPair = True
                    self._updateRunningHandlers()
            elif isinstance(handler, pjs.handlers.base.ThreadedHandler):
                self._execThreadedHandler(handler)
                return True
            else:
                logging.warning("Unknown handler type (%s) for %s",
                                type(handler), handler)
                
        return False
    
    def setNextHandler(self, handlerName, errorHandlerName=None):
        """Schedules 'handlerName' as the next handler to execute. Optionally,
        also schedules 'errorHandlerName' as the next error handler.
        """
        handler = Dispatcher().getHandlerFunc(handlerName)
        if handler:
            self.handlers.insert(0, handler())
            if errorHandlerName:
                eHandler = Dispatcher().getHandlerFunc(errorHandlerName)
                if eHandler:
                    self.errorHandlers.insert(0, eHandler())
    
class _Dispatcher(object):
    """Dispatches events in a phase to Messages for handling. This class
    uses the Singleton pattern.
    """
    def __init__(self):
        self.phasesList = corePhases
    
    def dispatch(self, tree, conn, knownPhase=None):
        """Dispatch a Message object to process the stanza.
        
        tree -- stanza expressed as ElementTree's Element. This will be wrapped
                with the <stream> Element to allow for XPath querying
        conn -- connection that called this dispatcher
        knownPhase -- the phase that this packet is in, if known.
        """
        phaseName = 'default'
        phase = self.phasesList[phaseName]
        
        if knownPhase and self.phasesList.has_key(knownPhase):
            phase = self.phasesList[knownPhase]
            phaseName = knownPhase
        else:
            # loop through all phases to find the one who's XPath expr matches
            # the stanza
            # FIXME: this is likely to be a bottleneck
            for p in self.phasesList:
                if self.phasesList[p].has_key('xpath') and tree.find(self.phasesList[p]['xpath']) is not None:
                    phase = self.phasesList[p]
                    phaseName = p
                    break

        # handlers get instantiated and loaded up into lists
        # TODO: watch for errors during instantiation
        # TODO: instantiate once, cache the handler and reuse
        if phase.has_key('handlers'):
            handlers = [item['handler']() for item in phase['handlers']]
            if phase.has_key('errorHandlers'):
                errorHandlers = [item['handler']() for item in phase['errorHandlers']]
            else:
                errorHandlers = []
        else:
            return
                
        msg = Message(tree, conn, handlers, errorHandlers, phaseName)
        msg.process()
    
    def getHandlerFunc(self, handlerName):
        """Gets a reference to the handler function"""
        if h.has_key(handlerName):
            return h[handlerName]['handler']
        else: return None

_dispatcher = _Dispatcher()
def Dispatcher(): return _dispatcher

class _StanzaDispatcher(_Dispatcher):
    """Stanza-specific dispatcher"""
    
    def __init__(self):
        self.phasesList = stanzaPhases

_stanzaDispatcher = _StanzaDispatcher()
def StanzaDispatcher(): return _stanzaDispatcher