#!/usr/bin/env python3

import os, sys, logging, configparser
import string, re, random
import time
from datetime import datetime
import smtplib
import dns.resolver
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

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
logfh = logging.FileHandler(__PROJECTNAME_ + '.log')
logfmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
logfh.setFormatter(logfmt)
log.addHandler(logfh)

class MailProxyHandler:
    def __init__(self, domain, host, user, port, relay_ip, relay_port):
        self._domain = domain
        self._host = host
        self._user = user
        self._port = port
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
            # relay just redirect mail intact
            # e = self.rtoe(envelope.rcpt_tos[0])
            self._mx = self.exchanger(envelope.rcpt_tos[0].split('@')[1])
            if not self._mx:
                log.warning('bad outbound address: ' + envelope.rcpt_tos[0])
                return '250 OK'
                
        refused = self._deliver(envelope)
        if refused:
            log.warning('recipients refused: %s', refused)

        return '250 OK'

    def _deliver(self, envelope):
        refused = {}
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
        except smtplib.SMTPRecipientsRefused as e:
            refused = e.recipients

        except (OSError, smtplib.SMTPException) as e:
            refused = envelope.rcpt_tos

        return refused
    
    # from mail line get mail address
    def rtoe(self, r):
        e = re.findall(EMAILWRAP, r)
        return e[0] if e else r
    
    # query MX record
    def exchanger(self, domain):
        mx = dns.resolver.query(domain, 'MX')
        return str(mx[0].exchange).rstrip('.') if mx else None
    
    # generate dkim
    def dkim(self):
        return ''
        
    # genereate messageid
    def messageid(self):
        return 'Message-ID: <_' + self.ranstr(36) + '@' + self._domain + '>'
        
    # generate received
    def received(self, emai, crlf):
        mid = []
        mid.append('Received: from timelegend.net (unknown [127.0.0.1])')
        mid.append('by smtp.timelegend.net (ESMTP) with SMTP id ' + self.ranstr(12))
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

        # construct envelope subject/from/tos
        subjectline = lines[marks['subject']['no']]
        subjectenc = re.search(SUBJECTTAG, subjectline)
        if subjectenc:
            subj = subjectline.lstrip(SUBJECT).rstrip(CRLF)
            ds = decode_header(subj.decode())
            ds1 = ds[0][0]
            
        if self._inbound is True:
            if subjectenc:
                ds1 = ds1 + ADDRESSGAP.format(envelope.mail_from).encode()
                subj = make_header([(ds1, ds[0][1])]).encode().encode()
                linesubject = SUBJECT + subj + CRLF
            else:
                linesubject = subjectline.replace(CRLF, ADDRESSGAP.format(envelope.mail_from).encode() + CRLF)
            envelope.mail_from = envelope.rcpt_tos[0]
            envelope.rcpt_tos = ["{}@{}".format(self._user, self._host)]
        else:
            envelope.mail_from = envelope.rcpt_tos[0]
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
        
        # headers.append(self.dkim().encode() + CRLF)
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
        sts = (ST1, ST2)
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
        return True
        
        
if __name__ == '__main__':
    if len(sys.argv) == 2:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(sys.path[0], __PROJECTNAME_ + '.ini')

    if not os.path.exists(config_path):
        raise Exception("config file not found: {}".format(config_path))

    config = configparser.ConfigParser()
    config.read(config_path)
    
    __SERVER_MODE__ = config.getboolean('general', 'servermode')
    domain = config.get('server', 'domain')
    relay_ip = config.get('relay', 'ip')
    if not relay_ip:
        if __SERVER_MODE__:
            f = open(config.get('relay', 'ipfile'), 'r')
            relay_ip = f.readline()
            f.close()
    relay_bind = config.get('relay', 'bind', fallback = '0.0.0.0')
    relay_port = config.getint('relay', 'port', fallback = 2525)
    bind = config.get('server', 'bind', fallback = '0.0.0.0')
    port = config.getint('server', 'port', fallback = 25)
    
    controller = Controller(
        MailProxyHandler(
            domain = domain,
            host = config.get('remote', 'host'),
            user = config.get('remote', 'user'),
            port = config.getint('remote', 'port', fallback = 25),
            relay_ip = relay_ip,
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
