# What is tlmail
Runing a full functional mail service involves sophisticated setup and much maintain efforts. Many cloud providers also do not allow personnal mail services by blocking port `25`. This mail relay will let you own an email address of your domain, without runing a mail server. You can use the address to communicate with the world.

# How it works
First you need a cloud host configured as a server, which your domain targets to. Next you need a local host configured as a relay.
To send mail, send to the address of your domain from your public mail account. The mail will arrives at your server. The server redirects the mail to your relay. At last the relay redirects the mail to the targeting mail server.
To receive mail, the replied mail also arrives at your server first, then at your relay, finally at your public mail account.

# Prerequisite
* an account from public mail server, eg. gmail.com
* a cloud host service, eg. google cloud
* a domain name with MX record configured(optional DKIM TXT), targeting at the cloud host
* your local network

# Usage
1. On both server and relay
```
git clone https://github.com/lakedai/tlmail.git
cd tlmail
pip3 install dnspython aiosmtpd dkimpy
```
2. On server
- edit general and server sections of config file `tlmail.ini`
- open port `25` of the server
- run:
```
sudo python3 tlmail.py &
```
3. On relay
edit general, relay and remote section of config file `tlmail.ini`
open port `2525` of the relay
run:
```
python3 tlmail.py &
```
4. Mail operation
You can send and receive mails from your public mail account.
When sending a mail:
- set the `To:` field to the address of your domain
- sourround the receiver's address with `###` in both sides, and inject it to the `Subject:` field
