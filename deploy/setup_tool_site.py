# -*- coding: utf-8 -*-
"""
为班级小工具站开独立门牌：https://tool.furina.fun
  1) 香港 OSS 新建 bucket tool-furina-fun（公共读 + 静态网站托管）
  2) 上传 tools/index.html + assets/**
  3) Let's Encrypt 签发 tool.furina.fun 证书（DNS-01，走阿里云 DNS）
  4) 绑定自定义域名（_dnsauth 校验 + CNAME 记录）
可重复执行（幂等）。用法：python setup_tool_site.py
"""
import os, json, time, datetime, subprocess, sys

import oss2
from oss2.models import BucketWebsite, PutBucketCnameRequest, CertInfo
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

AK = os.environ.get("ALIYUN_AK_ID"); SK = os.environ.get("ALIYUN_AK_SECRET")
if not AK or not SK:
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "creds.env")
    _d = {}
    for _l in open(_p, encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            _d[_k.strip()] = _v.strip()
    AK = _d.get("ALIYUN_AK_ID"); SK = _d.get("ALIYUN_AK_SECRET")
if not AK or not SK:
    raise SystemExit("缺少凭据：环境变量或同目录 creds.env")
REGION = "oss-cn-hongkong"; EP = "https://%s.aliyuncs.com" % REGION
BUCKET = "tool-furina-fun"
DOMAIN = "tool.furina.fun"
ZONE = "furina.fun"
RR = "tool"
EMAIL = "3299207275@qq.com"
DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "tools"))
CERTDIR = os.path.join(SRC, "cert")
os.makedirs(CERTDIR, exist_ok=True)

cli = AcsClient(AK, SK, "cn-hangzhou")


def dns(action, params):
    r = CommonRequest(); r.set_domain("alidns.aliyuncs.com"); r.set_version("2015-01-09")
    r.set_action_name(action); r.set_method("POST")
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


def set_txt(rr, value, keep=False):
    """写入 TXT 记录（先删同名旧记录）"""
    cur = dns("DescribeDomainRecords", {"DomainName": ZONE, "RRKeyWord": rr, "Type": "TXT"})
    for x in cur.get("DomainRecords", {}).get("Record", []):
        if x["RR"] == rr:
            dns("DeleteDomainRecord", {"RecordId": x["RecordId"]})
            print("   删除旧 TXT", rr, x["Value"][:28])
    if not keep:
        res = dns("AddDomainRecord", {"DomainName": ZONE, "RR": rr, "Type": "TXT", "Value": value, "TTL": "600"})
        print("   TXT 写入", rr, "->", res.get("RecordId"))


def wait_txt(rr, expect, timeout=180):
    """轮询 8.8.8.8，等 TXT 生效"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            out = subprocess.run(["nslookup", "-type=TXT", "%s.%s" % (rr, ZONE), "8.8.8.8"],
                                 capture_output=True, text=True, timeout=20).stdout
            if expect[:20] in out.replace('"', ''):
                print("   DNS 已生效 (%.0fs)" % (time.time() - t0))
                return True
        except Exception:
            pass
        time.sleep(8)
    print("   !! DNS 等待超时，继续尝试")
    return False


print("=== 1. Bucket ===")
auth = oss2.Auth(AK, SK)
svc = oss2.Service(auth, EP)
existing = {b.name for b in oss2.BucketIterator(svc)}
bucket = oss2.Bucket(auth, EP, BUCKET)
if BUCKET not in existing:
    try:
        bucket.create_bucket(permission=oss2.BUCKET_ACL_PUBLIC_READ)
        print("   created (public-read):", BUCKET)
    except Exception as e:
        print("   public-read create failed:", type(e).__name__, e)
        bucket.create_bucket(permission=oss2.BUCKET_ACL_PRIVATE)
        print("   created (private)")
else:
    print("   bucket 已存在，复用:", BUCKET)
try:
    bucket.put_bucket_public_access_block(False)
    print("   public access block -> off")
except Exception as e:
    print("   warn public-access-block:", type(e).__name__, e)
try:
    bucket.put_bucket_acl(oss2.BUCKET_ACL_PUBLIC_READ)
    print("   acl -> public-read")
except Exception as e:
    print("   warn acl:", type(e).__name__, e)
bucket.put_bucket_website(BucketWebsite(index_file="index.html", error_file="index.html"))
print("   静态网站托管 on (index.html)")

print("=== 2. 上传 ===")
H = {".html": "text/html; charset=utf-8", ".png": "image/png", ".css": "text/css; charset=utf-8",
     ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8"}
names = ["index.html"] + [("assets/" + f) for f in sorted(os.listdir(os.path.join(SRC, "assets")))]
for name in names:
    p = os.path.join(SRC, name.replace("/", os.sep))
    ext = os.path.splitext(name)[1].lower()
    bucket.put_object_from_file(name, p, headers={"Content-Type": H.get(ext, "application/octet-stream"),
                                                  "Cache-Control": "no-cache"})
    print("   %-24s %7d bytes" % (name, os.path.getsize(p)))

print("=== 3. 证书（Let's Encrypt DNS-01）===")
import josepy as jose
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
from acme import client, messages

kf = os.path.join(HERE, "acme_account_key.pem")
acct_key_pem = open(kf, "rb").read()
acc_key = jose.JWKRSA(key=serialization.load_pem_private_key(acct_key_pem, None))
net = client.ClientNetwork(acc_key, user_agent="ziqi-deploy/1.0")
directory = messages.Directory.from_json(net.get(DIRECTORY).json())
ac = client.ClientV2(directory, net=net)
regr = None
try:
    regr = ac.new_account(messages.NewRegistration.from_data(email=EMAIL, terms_of_service_agreed=True))
    print("   account created")
except Exception as e:
    print("   new_account:", type(e).__name__, "-> 查现有账号")
    reg = messages.RegistrationResource(
        body=messages.NewRegistration.from_data(email=EMAIL, terms_of_service_agreed=True), uri=None)
    regr = ac.query_registration(reg)
if regr is not None:
    ac.net.account = regr
    print("   account uri:", regr.uri)
dkf = os.path.join(CERTDIR, "domain.key")
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
orderr = ac.new_order(csr.public_bytes(serialization.Encoding.PEM))
authz = orderr.authorizations[0]
challb = next(c for c in authz.body.challenges if c.chall.typ == "dns-01")
txt_val = challb.chall.validation(acc_key)
acme_rr = "_acme-challenge." + RR
set_txt(acme_rr, txt_val)
wait_txt(acme_rr, txt_val)
ac.answer_challenge(challb, challb.chall.response(acc_key))
deadline = datetime.datetime.now() + datetime.timedelta(seconds=180)
orderr = ac.poll_authorizations(orderr, deadline)
print("   authz:", orderr.authorizations[0].body.status)
orderr = ac.poll_and_finalize(orderr, deadline)
pem = orderr.fullchain_pem
open(os.path.join(CERTDIR, "fullchain.pem"), "w", encoding="utf-8").write(pem)
print("   证书已签发:", pem.splitlines()[0], len(pem), "bytes")

print("=== 4. 绑定自定义域名 ===")
tok = bucket.create_bucket_cname_token(DOMAIN)
token = getattr(tok, "token", None) or getattr(tok, "cname_token", None)
print("   cname token:", str(token)[:24], "...")
set_txt("_dnsauth." + RR, token)
wait_txt("_dnsauth." + RR, token)

cur = dns("DescribeDomainRecords", {"DomainName": ZONE, "RRKeyWord": RR, "Type": "CNAME"})
for x in cur.get("DomainRecords", {}).get("Record", []):
    if x["RR"] == RR:
        dns("DeleteDomainRecord", {"RecordId": x["RecordId"]})
        print("   删除旧 CNAME", RR)
cname_target = "%s.%s.aliyuncs.com" % (BUCKET, REGION)
res = dns("AddDomainRecord", {"DomainName": ZONE, "RR": RR, "Type": "CNAME", "Value": cname_target, "TTL": "600"})
print("   CNAME", RR, "->", cname_target, res.get("RecordId"))

cert_info = CertInfo(certificate=pem, private_key=open(dkf, "rb").read().decode("utf-8"), force=True)
try:
    bucket.put_bucket_cname(PutBucketCnameRequest(DOMAIN, cert=cert_info))
    print("   put_bucket_cname OK（含证书）")
except Exception as e:
    print("   !! put_bucket_cname 失败:", type(e).__name__, e)
    try:
        bucket.put_bucket_cname(PutBucketCnameRequest(DOMAIN))
        print("   put_bucket_cname OK（无证书）")
    except Exception as e2:
        print("   !! 仍失败:", type(e2).__name__, e2)

print("=== 完成，等 DNS/证书生效后访问 https://%s/ ===" % DOMAIN)
