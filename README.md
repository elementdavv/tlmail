# What is tlmail
Runing a full functional mail service involves sophisticated setup and much maintain efforts. Many cloud providers also do not allow personnal mail services by prohibiting port `25`. This mail relay script will let you own an email address of your personal domain, without runing a whole mail server. You can use the address to communicate with the world. For others, they write to a personal mailbox, instead of a public one like gmail or yahoo mail.

# How it works
For sending mail, from your public mail server, send a mail to an address of your ponsonal domain. That domain must be configured to target at your server by dns MX record. The server runs the script in server mode, it receives the mail and redirects it to your relay. The relay runs the script in relay mode, it then redirects the mail to the mail server of the real receiver directly.  
For receiving mail, the replied mail also arrives at your server first, then at relay, and arrives at your public mail server at last.

# Prerequisite
* a domain name with MX record configured(optional DKIM TXT)
* a cloud host to run server
* a adsl at home to run relay
* a public mail account

# Usage
1. Install  
At both server and relay, run:  
```
git clone https://github.com/lakedai/tlmail
cd tlmail
pip3 install dnspython aiosmtpd dkimpy
```
2. At server  
edit the config file `tlmail.ini`
open port `25`  
run:  
```
sudo python3 tlmail.py &
```
3. At relay  
edit the config file `tlmail.ini`
open port `2525`  
run:  
```
python3 tlmail.py &
```
4. Mail operation  
To send/receive mails, login to your public mail account.  
When sending a mail, set the `To:` field to an address of your domain, and embed the real receiver's address surrounded with `###` in both sides to the `Subject:` field.  
After receivers reply, you can receive and read them at the same place.  
