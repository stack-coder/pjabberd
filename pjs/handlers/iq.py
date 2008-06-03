import logging
import pjs.threadpool as threadpool

from pjs.handlers.base import ThreadedHandler, Handler, chainOutput, poll
from pjs.roster import Roster, RosterItem
from pjs.elementtree.ElementTree import Element, SubElement
from pjs.utils import tostring, generateId, FunctionCall
from pjs.db import DB

class IQBindHandler(Handler):
    """Handles resource binding"""
    def handle(self, tree, msg, lastRetVal=None):
        iq = tree[0]
        id = iq.get('id')
        if id:
            bind = iq[0]
            if len(bind) > 0:
                # accept id
                # TODO: check if id is available
                resource = bind[0].text
            else:
                # generate an id
                resource = generateId()[:6]
            
            # TODO: check that we don't already have such a resource
            
            msg.conn.data['user']['resource'] = resource
                
            res = Element('iq', {'type' : 'result', 'id' : id})
            bind = Element('bind', {'xmlns' : 'urn:ietf:params:xml:ns:xmpp-bind'})
            jid = Element('jid')
            jid.text = '%s/%s' % (msg.conn.data['user']['jid'], resource)
            bind.append(jid)
            res.append(bind)
            
            return chainOutput(lastRetVal, res)
        else:
            logging.warning("No id in <iq>:\n%s", tostring(iq))
            
        return lastRetVal
        
class IQSessionHandler(Handler):
    """Handles session establishment"""
    def handle(self, tree, msg, lastRetVal=None):
        res = Element('iq', {
                             'from' : msg.conn.server.hostname,
                             'type' : 'result',
                             'id' : tree[0].get('id')
                             })
        
        msg.conn.data['user']['in-session'] = True
        
        return chainOutput(lastRetVal, res)
    
class IQRosterGetHandler(ThreadedHandler):
    """Responds to a roster iq get request"""
    def __init__(self):
        # this is true when the threaded handler returns
        self.done = False
        # used to pass the output to the next handler
        self.retVal = None
    
    def handle(self, tree, msg, lastRetVal=None):
        self.done = False
        
        tpool = msg.conn.server.threadpool
        
        msg.conn.data['user']['requestedRoster'] = True
        
        # the actual function executing in the thread
        def act():
            # TODO: verify that it's coming from a known user
            jid = msg.conn.data['user']['jid']
            resource = msg.conn.data['user']['resource']
            id = tree[0].get('id')
            if id is None:
                logging.warning('[roster] No id in roster query. Tree: %s', tree[0])
                # TODO: throw exception here
                return
            
            c = DB().cursor()
            # get the contactid, name and subscriptions
            try:
                c.execute("SELECT roster.contactid, roster.name,\
                                  substates.primaryName subscription,\
                                  contactjids.jid cjid\
                           FROM roster\
                               JOIN jids AS userjids ON roster.userid = userjids.id\
                               JOIN jids AS contactjids ON roster.contactid = contactjids.id\
                               JOIN substates ON substates.stateid = roster.subscription\
                           WHERE userjids.jid = ?", (jid,))
            except Exception, e:
                print e
            
            roster = Roster()
            
            for row in c:
                roster.addItem(row['contactid'], RosterItem(row['cjid'], row['name'], row['subscription']))
            
            # get the groups now for each cid
            try:
                c.execute("SELECT rgi.contactid, rgs.name\
                           FROM rostergroups AS rgs\
                               JOIN rostergroupitems AS rgi ON rgi.groupid = rgs.groupid\
                               JOIN jids ON rgs.userid = jids.id\
                           WHERE jids.jid = ?", (jid,))
            except Exception, e:
                print e
            
            for row in c:
                roster.addGroup(row['contactid'], row['name'])
                
            c.close()
            
            res = Element('iq', {
                                 'to' : '/'.join([jid, resource]),
                                 'type' : 'result',
                                 'id' : id
                                 })
            
            res.append(roster.getAsTree())
            return chainOutput(lastRetVal, res)
        
        def cb(workReq, retVal):
            self.done = True
            # make sure we pass the lastRetVal along
            if retVal is None:
                self.retVal = lastRetVal
            else:
                self.retVal = retVal
                
        req = threadpool.makeRequests(act, None, cb)
        
        def checkFunc():
            # need to poll manually or the callback's never called from the pool
            poll(tpool)
            return self.done
        
        def initFunc():
            tpool.putRequest(req[0])
            
        return FunctionCall(checkFunc), FunctionCall(initFunc)
            
    
    def resume(self):
        # this is passed to the next handler
        return self.retVal

class IQNotImplementedHandler(Handler):
    """Handler that replies to unknown iq stanzas"""
    def handle(self, tree, msg, lastRetVal=None):
        if len(tree) > 0:
            # get the original iq msg
            origIQ = tree[0]
        else:
            logging.warning("Original <iq> missing:\n%s", tostring(tree))
            return
        
        id = origIQ.get('id')
        if id:
            res = Element('iq', {
                                 'type' : 'error',
                                 'id' : id
                                })
            res.append(origIQ)
            
            err = Element('error', {'type' : 'cancel'})
            SubElement(err, 'service-unavailable',
                       {'xmlns' : 'urn:ietf:params:xml:ns:xmpp-stanzas'})
            
            res.append(err)
            
            return chainOutput(lastRetVal, res)
        else:
            logging.warning("No id in <iq>:\n%s", tostring(origIQ))
        
        return lastRetVal