# coding=utf-8

"""
将本地的修改通过ftp一键同步到服务器上 ，非常适合维护一个网站并且经常改动代码的情况(监测文件变动依赖于版本控制系统)
usage: sync_web config.ini
author: ksc (http://blog.geekli.cn)
"""
import os,time,sys
import stat
import string
import subprocess
import shutil
import argparse
from ftplib import FTP
from ftplib import FTP_TLS as FTPS
import ConfigParser
script_path=sys.argv[0]
version= '2.2.0'
 
parser = argparse.ArgumentParser()
parser.add_argument('-v','--version', action='version', version=version, help="show program's version number and exit")
parser.add_argument('config_file',        default='config.ini', nargs='?',  help=u'配置文件路径')
parser.add_argument('-r', '--reversions', default='', nargs='?',help=u'同步指定版本中变动的文件列表（内容以本地文件为准）')
parser.add_argument('-P', '--prompt',     default=False,action='store_true',help=u'是否显示需要同步的文件列表')

args = parser.parse_args()
#print args;quit()    
config_file=args.config_file
if os.path.isabs(config_file)==False:#若是相对路径，则转化为绝对的
    config_file=os.path.realpath(os.getcwd()+os.sep+config_file)

print('config: '+config_file )
    
if os.path.isfile(config_file)==False:
    print('config file does not exist')
    sys.exit()    

conf={}
cf = ConfigParser.ConfigParser()
try:
    cf.read(config_file)
    local_webroot =cf.get('local','local_webroot')
    conf['log_file'] = cf.get('local','log_file')
    conf['prompt'] = False #prompt before every sync
    conf['local_backup_path'] = False  
    conf['exclude_path'] = [] 
    
    if cf.has_option('local','prompt'):
        conf['prompt']=cf.getboolean('local','prompt')
    
    if cf.has_option('local','local_backup_path'):
        conf['local_backup_path']=cf.get('local','local_backup_path')
        
    if cf.has_option('local','exclude_path'):
        conf['exclude_path']=string.split(cf.get('local','exclude_path'),',')

except Exception as e:
    print('Parse config file failed')
    print(e)
    sys.exit()
    
#本地项目目录
local_webroot=os.path.realpath(local_webroot)+os.sep

os.chdir(local_webroot)

IS_SVN=False
if os.path.isdir(local_webroot+'.svn'):
    IS_SVN=True
elif os.path.isdir(local_webroot+'.git'):
    IS_SVN=False
else:
    print('no version control')
    sys.exit()
    
#依赖版本控制系统获取变动文件列表
def getChangeFiles():
    """
        Returns:
            file 文件的相对路径 ，op 目前没有用到
            example: [{'file': 'upload/images/a.jpg', 'op': '?'},...]
    """
    global local_webroot
    if IS_SVN:
        sh='svn st'
    else:
        sh='git status -s'
        

    #导出修改的文件列表
    pipe=subprocess.Popen(sh, shell=True,stdout=subprocess.PIPE)
    pipe.wait()
    if pipe.returncode > 0:
        sys.exit()
    files=[]
    for line in pipe.stdout:
        line=line.rstrip()
        #print(line)
        if IS_SVN:
            if line=='':
                break
            op=line[0:1]    
            if line[8:]!='.' and op in ['A','M']:
                files.append({'op':op ,'file':line[8:]})
            
        else:
            files.append({'op':line[0:3],'file':line[3:]})
    return files
    
def getReversionsFile(version):
    """只上传指定版本修改的文件
    """
    if IS_SVN:
        sh=['svn','log','-v','-r',str(version)]
    else:
        sh=['git', 'log', version, '--name-status', '--pretty=format:"%H - %an, %ad : %s"', '-1']
    pipe=subprocess.Popen(sh, stdout=subprocess.PIPE)
    pipe.wait()
    if pipe.returncode > 0:
        sys.exit()
    files=[]
    for line in pipe.stdout:
        line=line.strip()
        #print(line)
        if line=='':
            break
        op=line[0:1]    
        if line[8:]!='.' and op in ['A','M']:
            files.append({'op':op ,'file':line[2:]})
    return files

def writeLogs(str,showTime = False ):
    global conf
    if conf['log_file']=='':
        return
    if showTime:
        str=time.strftime('%Y-%m-%d %H:%M:%S')+'  '+str+'\n'
    f=open(conf['log_file'],'a+')
    f.write(str)
    f.close()

#遍历目录
def walk_path(top):
    """ 
    Args:
        top: 相对web根目录的相对路径 
    Returns:
        该目录下的所有文件列表的一个数组
        格式同 getSvnFiles()的返回值
        example:[{'file': 'upload/images/a.jpg', 'op': '?'},...]
    """

    flist=[]
    for root, dirs, files in os.walk(top, topdown=False):
        for name in files:
            f=os.path.join(root, name)
            flist.append({'op':'a','file':f})
    return flist        


#获取不依赖[版本控制]监测变动的文件列表
def getKcFiles():
    global cf
    if cf.has_option('local','paths')==False:
        return []
    flist=[]
    paths=cf.get('local','paths')
    paths=string.split(paths,',')
    for path in paths:
        if os.path.isfile(path):
            flist.append({'op':'a','file':path})
        else:
            flist.extend(walk_path(path))
    return flist

def tagExcludeFile(item):
    """标记被排除的目录中的文件"""
    global conf
    for _path in conf['exclude_path']:
        if _path==item['file'][0:len(_path)].replace('\\','/'):
            item['op']='ex'
    return item    
        
def prompt_sync(filelist):
    
    for f in filelist:
        if f['op']!='ex':
            print( f['file'])
    y=raw_input('start sync?[Y/n]\n')
    if string.strip(y)=='n':
        sys.exit()

def clearLocalBackupPath(backupPath):  

    if not os.path.isdir(backupPath):
        return
    confirmFile=os.path.join(backupPath,'confirm_remove_allfile')    
    if not os.path.isfile(confirmFile):
        y=raw_input('delete all file in %s ?[Y/n]\n'%backupPath)
        if string.strip(y)=='n':
            return 
    shutil.rmtree(backupPath)
    os.mkdir(backupPath)
  
    open(confirmFile,'w').close()
    
def saveChangedFile(backupPath, filelist):
    #print('start backup')
    for file in filelist:
        
        file=file.get('file')
        src_file=os.path.join(local_webroot,file)
        if not os.path.isfile(src_file):
            continue
        #print(file)
        dst_file=os.path.join(backupPath, file)
        dst_path=os.path.dirname(dst_file)
        if not os.path.isdir(dst_path):
            #print('mkdir:'+dst_path)
            os.makedirs(dst_path)
        shutil.copyfile(src_file, dst_file)
    print('Backup done')
    #quit();
  
class Ftp_sync:
    uploadFileList=[]#本次上传的文件列表
    checkMTime=True#是否检查文件修改时间
    def __init__(self,ftp_name):
        global config_file,local_webroot,cf
        self.bufsize = 1024
        self.cf = cf
        self.config_file = config_file
        self.local_webroot = local_webroot
        self.ftp_name = ftp_name
        try:
            self.ftp_host    = cf.get(ftp_name,'host')
            self.ftp_port    = cf.get(ftp_name,'port')
            self.ftp_user    = cf.get(ftp_name,'user')
            self.ftp_passwd  = cf.get(ftp_name,'passwd')
            self.ftp_webroot = cf.get(ftp_name,'webroot')
            self.ftp_ssl     = cf.getboolean(ftp_name,'ssl')
            self.automkdir   = cf.getboolean(ftp_name,'automkdir')
        except Exception as e:
            print('Parse config file failed in ['+ftp_name+']')
            print(e)
            sys.exit()
        self.lastUploadTime=self.getLastTime()
        self.filelist=[]
    
    def setFileList(self,filelist):
        """ 设置需要同步的文件列表"""
        self.filelist=filelist
        
    def getLastTime(self):
        """返回最后一次同步的时间"""
        try:
            ltime= cf.getfloat(self.ftp_name,'lasttime')
        except:
            return 0
        return ltime
        
    def setLastTime(self):
        """设置最后一次同步的时间"""
        self.cf.set(self.ftp_name, "lasttime", time.time())
        self.cf.set("var", "lasttime", time.time())
        self.cf.write(open(self.config_file, "w"))
        
    def connect(self):
        #初始化 FTP 链接
        if self.ftp_ssl:
            ftp = FTPS()
        else:
            ftp = FTP()
        print('-'*20+self.ftp_name+'-'*20)
        print('connect '+('ftps' if self.ftp_ssl else 'ftp')+'://'+self.ftp_host+':'+self.ftp_port)
        try:
            ftp.connect(self.ftp_host,self.ftp_port)
        except Exception as e:
            print (e)
            print ('connect ftp server failed')
            sys.exit()
        try:
            ftp.login(self.ftp_user,self.ftp_passwd)
            print ('login ok')
        except Exception as e:#可能服务器不支持ssl,或者用户名密码不正确
            print (e)
            print ('Username or password are not correct')
            sys.exit()        
        
        if self.ftp_ssl:
            try:    
                ftp.prot_p()
            except Exception as e:
                print (e)
                print ('Make sure the SSL is on ;')
            
        print(ftp.getwelcome())
        ftp.cwd(self.ftp_webroot)
        print('current path: '+ftp.pwd())
        
        self.ftp=ftp
    
    def sync(self):
        _uploadNum = 0
        _bufsize=1024
       
        writeLogs('\n\n'+'start sync '+self.ftp_name+'\n')
        print('-'*20)
        for line in self.filelist:
            file=line['file'] 
            file= file.replace('\\','/')
            fullname=self.local_webroot+file
            if line['op']=='ex':
                continue
            if not os.path.isfile(fullname):
                continue
             
            _st=os.stat(fullname)
            st_mtime = _st[stat.ST_MTIME]
            
            if not self.checkMTime or st_mtime > self.lastUploadTime:#如果不检查文件修改时间 或 从上次上传后，文件修改过
     
                _uploadNum=_uploadNum+1
                writeLogs(fullname,True)
                self.uploadFileList.append(file)
                print(file)
                file_handler = open(fullname,'rb')
                ftp_file=self.ftp_webroot+file
                try:
                    self.ftp.storbinary('STOR '+ftp_file,file_handler,_bufsize) 
                except Exception as e:
                    #print(e)
                    if self.automkdir== False:
                        sys.exit()
                    else:# make dir and try again
                        try:
                            print('try mkdir: '+os.path.dirname(file))
                            ftpdirs=os.path.dirname(file).split('/')
                            for _ftpdir in ftpdirs:
                                try:
                                    self.ftp.mkd(_ftpdir)
                                except:
                                    pass #忽略创建目录的错误
                                self.ftp.cwd(_ftpdir)                               
                            self.ftp.cwd(self.ftp_webroot)
                            self.ftp.storbinary('STOR '+ftp_file,file_handler,_bufsize) 
                            print('retry success')
                        except Exception as e:
                            print(e)
                            sys.exit()
                finally:        
                    file_handler.close()
                        
        self.setLastTime()            
        self.ftp.quit()
        if  _uploadNum >0:
            writeLogs('共上传'+str(_uploadNum)+'个文件')
        else:
            writeLogs('没有上传文件')
        print('success');
     
if args.reversions=='':     
    filelist=getChangeFiles()
    filelist.extend(getKcFiles())
else:
    filelist=[]
    for _reversions in args.reversions.split(','):
        filelist.extend(getReversionsFile(_reversions))
    
if conf['exclude_path']!=[]:
    filelist=map(tagExcludeFile,filelist)

if conf['prompt'] or args.prompt:
    prompt_sync(filelist)
    

if conf['local_backup_path']:
    clearLocalBackupPath(conf['local_backup_path'])
    saveChangedFile(conf['local_backup_path'], filelist)
    
for ftp in cf.sections():
    if ftp[0:3]=='ftp':
        sync=Ftp_sync(ftp)
        if args.reversions:
            sync.checkMTime=False
        sync.setFileList(filelist)
        sync.connect()
        sync.sync()

time.sleep(2)

