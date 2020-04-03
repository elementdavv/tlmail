#!/usr/bin/env python3

import os, sys, logging, configparser
import string, re, random
import time
from datetime import datetime
import smtplib
import dns.resolver
import dkim
from email.header import decode_header, make_header
from aiosmtpd.controller import Controller

__PROJECTNAME_	= 'tlmail'

__X_MAILER__ 	= b'tlmailer [ http://timelegend.net ] 1.0'
EMPTYBYTES 	= b''
ST1 		= b'\t'
ST2 		= b' '
NLCRE 		= b'^[\r\n|\r|\n]$'
DATEE 		= b'Date: '
FROM 		= b'From: '
ENVELOPEFROM 	= b'Envelope-From: '
TO 		= b'To: '
SUBJECT 	= b'Subject: '
XMAILER 	= b'X-Mailer: '
CTE 		= b'Content-Transfer-Encoding: '
CT 		= b'Content-Type: '
MIMEVERSION 	= b'Mime-Version: 1.0'
ADDRESSWRAP 	= b'###(.+)###'
ADDRESSGAP 	= '###{}###'
SUBJECTTAG 	= b'=\?.+\?[b|B]\?'
EMAILWRAP 	= '<(.+)>'

#logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
logfh = logging.FileHandler(__PROJECTNAME_ + '.log')
logfmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
logfh.setFormatter(logfmt)
log.addHandler(logfh)

class MailProxyHandler:
    def __init__(self, domain, host, user, use_dkim, port, dkim_selector, dkim_key, relay_ip, relay_port):
        self._domain = domain
        self._host = host
        self._user = user
        self._use_dkim = use_dkim
        self._port = port
        self._dkim_selector = dkim_selector
        self._dkim_key = dkim_key
        self._relay_ip = relay_ip
        self._relay_port = relay_port

    async def handle_MAIL(self, server, session, envelope, address, options):
        envelope.mail_options.extend(options)
        envelope.mail_from = address

        if __SERVER_MODE__:
            if address.find(self._host) == -1:
                self._inbound = True
                log.info('inbound >>>')
            else:
                self._inbound = False
                log.info('outbount >>>')

        return '250 OK'
        
    async def handle_RCPT(self, server, session, envelope, address, options):
        envelope.rcpt_options.extend(options)
        envelope.rcpt_tos.append(address)
        
        if __SERVER_MODE__:
            if address.find(self._domain) == -1:
                log.warning('notme >>> ' + address)
                return '550 Rejected domain mismatch'

        return '250 OK'

    async def handle_DATA(self, server, session, envelope):
        if __SERVER_MODE__:
        
            # all transmations done at server
            if not self.parse(envelope):
                return '250 OK'

        else:
            # relay just redirect intact
            self._mx = self.exchanger(envelope.rcpt_tos[0].split('@')[1])
            if not self._mx:
                log.warning('bad outbound address: ' + envelope.rcpt_tos[0])
                return '250 OK'
                
        self._deliver(envelope)

        return '250 OK'

    def _deliver(self, envelope):
        try:
            s = smtplib.SMTP()
            if __SERVER_MODE__:
                s.connect(host=self._relay_ip, port=self._relay_port)
                s.ehlo()
                try:
                    refused = s.sendmail(
                        envelope.mail_from,
                        envelope.rcpt_tos,
                        self._content,
                    )
                finally:
                    s.quit()
            else:
                s.connect(host=self._mx, port=self._port)
                s.ehlo()
                try:
                    refused = s.sendmail(
                        envelope.mail_from,
                        envelope.rcpt_tos,
                        envelope.original_content,
                    )
                finally:
                    s.quit()

        except (smtplib.SMTPConnectError,
                smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused,
                smtplib.SMTPDataError, 
                smtplib.SMTPException) as e:
            log.error(e.message)

    # from/to mail line get mail address
    def rtoe(self, r):
        e = re.findall(EMAILWRAP, r)
        return e[0] if e else r
    
    # query MX record
    def exchanger(self, domain):
        mx = dns.resolver.query(domain, 'MX')
        return str(mx[0].exchange).rstrip('.') if mx else None
    
    # generate dkim
    def dkim(self, content):
        return dkim.sign(message = content, 
                         selector = self._dkim_selector.encode(), 
                         domain = self._domain.encode(), 
                         privkey = self._dkim_key.encode(),
                         include_headers = ['From', 'To', 'Subject'])
        
    # genereate messageid
    def messageid(self):
        return 'Message-ID: <_' + self.ranstr(36) + '@' + self._domain + '>'
        
    # generate received
    def received(self, emai, crlf):
        mid = []
        mid.append('Received: from ' + self._domain + ' (unknown [127.0.0.1])')
        mid.append('by smtp.' + self._domain + ' (ESMTP) with SMTP id ' + self.ranstr(12))
        mid.append('for <' + emai + '>; ' + self.curtime())
        return (crlf.decode() + '\t').join(mid) 
        
    # generate current time string
    def curtime(self):
        return datetime.now().strftime('%a, %d %b %Y %H:%M:%S ') + time.strftime('%z') + ' (' + time.tzname[0] + ')'
        
    # genereate random string
    def ranstr(self, n):
        return ''.join(random.sample(string.ascii_letters + string.digits, n))
        
    # repackage mail message
    def parse(self, envelope):
        if isinstance(envelope.content, str):
            content = envelope.original_content
        else:
            content = envelope.content

        lines = content.splitlines(keepends=True)
        
        # search following fields line number
        marks = {
            # 'xmailer':         {'tag': XMAILER,       'no': -1},
            # 'from':            {'tag': FROM,          'no': -1},
            # 'envelope_from':   {'tag': ENVELOPEFROM,  'no': -1},
            'to':              {'tag': TO,            'no': -1},
            'subject':         {'tag': SUBJECT,       'no': -1},
        }

        i = 0
        for line in lines:
            if re.search(NLCRE, line):
                CRLF = line
                break
            for k, v in marks.items():
                if v['no'] == -1:
                    if line.startswith(v['tag']):
                        v['no'] = i
                        break
            i += 1
            
        # if subject is multiline
        sts = (ST1, ST2)
        si = marks['subject']['no']
        subjectline = lines[si]
        cont = True
        while cont:
            cont = False
            si += 1
            for st in sts:
                if lines[si].startswith(st):
                    subjectline += lines[si]
                    cont = True
                    break
        
        # construct envelope subject/from/tos
        subjectenc = re.search(SUBJECTTAG, subjectline)
        if subjectenc:
            subj = subjectline.lstrip(SUBJECT).rstrip(CRLF)
            ds = decode_header(subj.decode())
            ds1 = ds[0][0]
            
        if self._inbound is True:
            if subjectenc:
                ds1 = ds1 + ADDRESSGAP.format(self.rtoe(envelope.mail_from)).encode()
                subj = make_header([(ds1, ds[0][1])]).encode().encode()
                linesubject = SUBJECT + subj + CRLF
            else:
                linesubject = subjectline.replace(CRLF, ADDRESSGAP.format(self.rtoe(envelope.mail_from)).encode() + CRLF)
            envelope.mail_from = self.rtoe(envelope.rcpt_tos[0])
            envelope.rcpt_tos = ["{}@{}".format(self._user, self._host)]
        else:
            envelope.mail_from = self.rtoe(envelope.rcpt_tos[0])
            if subjectenc:
                envelope.rcpt_tos = re.findall(ADDRESSWRAP.decode(), ds1.decode())
                ds1 = re.sub(ADDRESSWRAP, b'', ds1)
                subj = make_header([(ds1, ds[0][1])]).encode().encode()
                linesubject = SUBJECT + subj + CRLF
            else:
                envelope.rcpt_tos = re.findall(ADDRESSWRAP.decode(), subjectline.decode())
                linesubject = re.sub(ADDRESSWRAP, b'', subjectline)

            # handle subject error
            if len(envelope.rcpt_tos) == 0:
                log.warning('bad outbound address: ')
                log.warning(ds1.decode() if subjectenc else subjectline.decode())
                return False
                
        # make header
        headers = []

        linexmailer = XMAILER + __X_MAILER__ + CRLF
        linefrom = lines[marks['to']['no']].replace(TO, FROM)
        lineenvelopefrom = linefrom.replace(FROM, ENVELOPEFROM)
        lineto = TO + envelope.rcpt_tos[0].encode() + CRLF
        
        headers.append(self.messageid().encode() + CRLF)
        headers.append(self.received(envelope.rcpt_tos[0], CRLF).encode() + CRLF)
        headers.append(linexmailer)
        headers.append(linefrom)
        headers.append(lineenvelopefrom)
        headers.append(lineto)
        headers.append(linesubject)
        headers.append(MIMEVERSION + CRLF)
        headers.append(DATEE + self.curtime().encode() + CRLF)
        
        # header plus content
        tags = (CTE, CT)
        cont = False
        other = False
        for line in lines:
            if other:
                headers.append(line)
                continue
            if re.search(NLCRE, line):
                headers.append(line)
                other = True
                continue
            if cont:
                cont = False
                for st in sts:
                    if line.startswith(st):
                        headers.append(line)
                        cont = True
                        break
                if cont:
                    continue
            for tag in tags:
                if line.startswith(tag):
                    headers.append(line)
                    cont = True
                    break
                    
        # envelope content
        self._content = EMPTYBYTES.join(headers)
        if dkim_selector:
            if (not self._inbound) or self._use_dkim:
                dkim = self.dkim(self._content)
                self._content = dkim + self._content
            
        return True
        
        
if __name__ == '__main__':
    if len(sys.argv) == 2:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(sys.path[0], __PROJECTNAME_ + '.ini')

    if not os.path.exists(config_path):
        log.warning('no config file')
        sys.exit()
        
    config = configparser.ConfigParser()
    config.read(config_path)
    
    __SERVER_MODE__ = config.getboolean('general', 'servermode', fallback = False)
    domain = config.get('server', 'domain')
    if not domain:
        log.warning('please set domain in config file')
        sys.exit()
    if __SERVER_MODE__:
        dkim_selector = config.get('server', 'dkim_selector')
        if dkim_selector:
            dkim_keyfile = config.get('server', 'dkim_keyfile')
            if not dkim_keyfile:
                log.warning('please set dkim_keyfile in config file')
                sys.exit()
            with open(dkim_keyfile, 'r') as f:
                dkim_key = f.read()
        else:
            dkim_key = None
            log.info('no dkim-signature')
        relay_ip = config.get('server', 'relay_ip')
        if not relay_ip:
            relay_ipfile = config.get('server', 'relay_ipfile')
            if not relay_ipfile:
                log.warning('please set relay_ip or relay_ipfile in config file')
                sys.exit()
            with open(relay_ipfile, 'r') as f:
                relay_ip = f.read()
    relay_bind = config.get('relay', 'bind', fallback = '0.0.0.0')
    relay_port = config.getint('relay', 'port', fallback = 2525)
    bind = config.get('server', 'bind', fallback = '0.0.0.0')
    port = config.getint('server', 'port', fallback = 25)
    
    host = config.get('remote', 'host')
    if not host:
        log.warning('please set host in config file')
        sys.exit()
    user = config.get('remote', 'user')
    if not user:
        log.warning('please set user in config file')
        sys.exit()

    controller = Controller(
        MailProxyHandler(
            domain = domain,
            host = host,
            user = user,
            use_dkim = config.getboolean('remote', 'use_dkim', fallback = True),
            port = config.getint('remote', 'port', fallback = 25),
            dkim_selector = dkim_selector if __SERVER_MODE__ else None,
            dkim_key = dkim_key if __SERVER_MODE__ else None,
            relay_ip = relay_ip if __SERVER_MODE__ else None,
            relay_port = relay_port,
        ),
        hostname = bind if __SERVER_MODE__ else relay_bind,
        port = port if __SERVER_MODE__ else relay_port,
    )
    
    controller.start()
    
    if __SERVER_MODE__:
        log.info('start serving at port %s', port)
    else:
        log.info('start relaying at port %s', relay_port)

    while controller.loop.is_running():
        time.sleep(0.2)
