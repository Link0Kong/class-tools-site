for p in ['CLOUDBASE.md','CHANGELOG.md']:
    s=open(p,encoding='utf-8').read()
    s=s.replace('学号规则：`32607070 + 两位座号`（01 → 3260707001）。','学号规则由班级名单维护者掌握。')
    s=s.replace('真实姓名 + 10 位学号（32607070 + 两位座号）','真实姓名 + 10 位学号')
    open(p,'w',encoding='utf-8').write(s)
print('ok')
