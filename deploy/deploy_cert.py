# -*- coding: utf-8 -*-
"""用 Let's Encrypt 为 me.furina.fun 签发证书（DNS-01，走阿里云 DNS 自动加 TXT）。"""
import os, json, time, datetime
import josepy as jose
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
from acme import client, messages, challenges
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

AK = os.environ["ALIYUN_AK_ID"]; SK = os.environ["ALIYUN_AK_SECRET"]
DOMAIN = "me.furina.fun"; ZONE = "furina.fun"
EMAIL = "3299207275@qq.com"
DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "..", "ziqi", "cert")
os.makedirs(OUTDIR, exist_ok=True)

cli = AcsClient(AK, SK, "cn-hangzhou")
def dns(action, params):
    r = CommonRequest(); r.set_domain("alidns.aliyuncs.com"); r.set_version("2015-01-09")
    r.set_action_name(action); r.set_method("POST")
    for k, v in params.items(): r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))

# ---------- 1. 账号密钥 ----------
kf = os.path.join(HERE, "acme_account_key.pem")
if os.path.exists(kf):
    acct_key_pem = open(kf, "rb").read()
    acc_key = jose.JWKRSA(key=serialization.load_pem_private_key(acct_key_pem, None))
else:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    acct_key_pem = k.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
    open(kf, "wb").write(acct_key_pem)
    acc_key = jose.JWKRSA(key=k)

net = client.ClientNetwork(acc_key, user_agent="ziqi-deploy/1.0")
directory = messages.Directory.from_json(net.get(DIRECTORY).json())
ac = client.ClientV2(directory, net=net)
new_reg = messages.NewRegistration.from_data(email=EMAIL, terms_of_service_agreed=True)
regr = None
try:
    regr = ac.new_account(new_reg)
    print("account created:", regr.uri)
except Exception as e:
    print("new_account:", type(e).__name__, str(e)[:120], "-> 查询现有账号")
    try:
        reg = messages.RegistrationResource(
            body=messages.NewRegistration.from_data(email=EMAIL, terms_of_service_agreed=True),
            uri=None)
        regr = ac.query_registration(reg)
    except Exception as e2:
        print("query_registration failed:", type(e2).__name__, str(e2)[:200])
if regr is not None:
    try:
        ac.net.account = regr
    except Exception as e:
        print("set account warn:", str(e)[:120])
    print("account uri:", regr.uri)
else:
    raise SystemExit("no account")

# ---------- 2. 域名密钥 + CSR ----------
dkf = os.path.join(OUTDIR, "domain.key")
if os.path.exists(dkf):
    dom_key = serialization.load_pem_private_key(open(dkf, "rb").read(), None)
else:
    dom_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    open(dkf, "wb").write(dom_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
csr = (x509.CertificateSigningRequestBuilder()
       .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DOMAIN)]))
       .add_extension(x509.SubjectAlternativeName([x509.DNSName(DOMAIN)]), critical=False)
       .sign(dom_key, hashes.SHA256()))
csr_pem = csr.public_bytes(serialization.Encoding.PEM)

# ---------- 3. 下单 ----------
orderr = ac.new_order(csr_pem)
print("order uri:", orderr.uri)
authz = orderr.authorizations[0]
challb = next(c for c in authz.body.challenges if c.chall.typ == "dns-01")
txt_val = challb.chall.validation(acc_key)
print("TXT value:", txt_val)

RR = "_acme-challenge.me"
cur = dns("DescribeDomainRecords", {"DomainName": ZONE, "RRKeyWord": RR, "Type": "TXT"})
old = [x for x in cur.get("DomainRecords", {}).get("Record", []) if x["RR"] == RR]
for x in old:
    dns("DeleteDomainRecord", {"RecordId": x["RecordId"]})
    print("deleted old TXT", x["Value"][:24])
res = dns("AddDomainRecord", {"DomainName": ZONE, "RR": RR, "Type": "TXT", "Value": txt_val, "TTL": "600"})
print("TXT added:", res.get("RecordId"))
time.sleep(30)

resp = challb.chall.response(acc_key)
ac.answer_challenge(challb, resp)
print("challenge answered")
deadline = datetime.datetime.now() + datetime.timedelta(seconds=180)
orderr = ac.poll_authorizations(orderr, deadline)
print("authz status:", orderr.authorizations[0].body.status)
orderr = ac.poll_and_finalize(orderr, deadline)
pem = orderr.fullchain_pem
open(os.path.join(OUTDIR, "fullchain.pem"), "w", encoding="utf-8").write(pem)
print("CERT SAVED:", os.path.join(OUTDIR, "fullchain.pem"), len(pem), "bytes")
print(pem.splitlines()[0])
