import glob, os, time, sys, fnmatch, subprocess, numpy, io, re, json
import scipy
import httplib, urllib
import matplotlib.pyplot as plt
import logging
import copy
import mrcfile

from PIL import Image
from datetime import datetime
import xml.etree.ElementTree as etree
from xml.etree.ElementTree import XML

#https://regexr.com/

#software_folder_regex={'EPU':'supervisor_\d{8}.*_EPU', 'TOMO4':'supervisor_\d{8}.*_TOMO4'}
software_folder_regex={'EPU':'supervisor_\d{8}.*', 'TOMO4':'supervisor_\d{8}.*_TOMO4'}
reg_ex_epu_micrograph='.*(GridSquare_\d*).*((FoilHole_\d*_Data_\d*_(\d*)_(\d*))_(\d*))_Fractions.mrc' #''(FoilHole_\d{7}_Data_\d{7}_\d{7}_(\d{8})_(\d{4})-(\d{5})).mrc'
# reg-ex falcon 3 linear (FoilHole_\d*_Data_\d*_(\d*)_(\d*))_(\d*).mrc
# reg-ex k2 linear '.*(GridSquare_\d*).*(FoilHole_\d*_Data_\d*_\d*_(\d*)_(\d*))-(\d*).mrc'
# example of tomography file format: Sarcomere_Tomo_1_042[60.00]-21270-0011.mrc

def mutt_mail (recip, subj, body_txt, attachments, mail_file):
    attach_string = ''
    for attachment in attachments:
        attach_string+= '-a {} '.format(attachment)

    mutt_cmd = 'mutt ' + '-s "' + subj + '" ' + recip + ' '+ attach_string

    if body_txt and mail_file:
        mail=open(mail_file, 'w')
        mail.write(body_txt)
        mail.close()
        mutt_cmd = mutt_cmd + ' < ' + mail_file

    try:
        sendmail_process = subprocess.Popen(mutt_cmd, shell=True)
        sendmail_process.wait()
    except Exception, error:
        print error

def pushover_message(APP_TOKEN, USER_KEY, MESSAGE, PRIORITY):
  conn = httplib.HTTPSConnection("api.pushover.net:443")
  conn.request("POST", "/1/messages.json",
    urllib.urlencode({
      "token": APP_TOKEN,
      "user": USER_KEY,
      "message": MESSAGE,
      "priority": PRIORITY,
    }), { "Content-type": "application/x-www-form-urlencoded" })
  conn.getresponse()

def tile_jpegs(image_list):
    images = map(Image.open, image_list)
    if len(images)==1:
        return images[0]
    elif len(images)>1:
        widths, heights = zip(*(i.size for i in images))
        total_width=sum(widths)
        max_height=max(heights)

        new_im = Image.new('RGB', (total_width, max_height))

        x_offset = 0
        for im in images:
          new_im.paste(im, (x_offset, 0))
          x_offset += im.size[0]
        return new_im

def delta_times_list(mlist_ctime_sorted, format):
    delta_list = []
    for index in range(0, len(mlist_ctime_sorted)):
        if index + 1 < len(mlist_ctime_sorted):
            delta = time_delta(time.ctime(mlist_ctime_sorted[index][1]), format,
                               time.ctime(mlist_ctime_sorted[index + 1][1]), format)
            delta_list.append(delta)
    delta_list_np = numpy.array(delta_list) / 60
    return delta_list_np

def poll_emsession(path):
  jpg_list=[]
  mrc_list=[]
  mrc_raw_list=[]
  xml_list=[]

  for root, dirnames, filenames in os.walk(path):
    if 'process' in root: continue

    for filename in fnmatch.filter(filenames, '*.jpg'):
      jpg_path=os.path.join(root,filename)
      jpg_list.append([jpg_path, os.path.getctime(jpg_path)])
    for filename in fnmatch.filter(filenames, '*.mrc'):
      mrc_path=os.path.join(root,filename)
      if 'raw' in root:
          mrc_raw_list.append([mrc_path, os.path.getctime(mrc_path)])
      else:
        mrc_list.append([mrc_path, os.path.getctime(mrc_path)])
    for filename in fnmatch.filter(filenames, '*.xml'):
      xml_path=os.path.join(root,filename)
      xml_list.append([xml_path, os.path.getctime(xml_path)])
  return mrc_list, mrc_raw_list , xml_list, jpg_list

def poll_dir(path, searchString):
  file_list=[]
  for root, dirnames, filenames in os.walk(path):
    for filename in fnmatch.filter(filenames, searchString):
        file_path=os.path.join(root,filename)
        file_list.append([file_path, os.path.getctime(file_path)])
  return file_list

def time_delta(ctime_1, format_1, ctime_2, format_2):
  """Return time difference between two points in seconds"""
  # time 1 is most recent
  time_1=datetime.strptime(ctime_1,format_1)
  time_2=datetime.strptime(ctime_2,format_2)
  delta_time=time_1-time_2
  return delta_time.total_seconds()

def search_for_dir(path, name):
    list_dirs=[]
    path_items=[]
    items = os.listdir(path)
    for item in items:
        path_items.append(os.path.join(path,item))

    for item in list(filter(os.path.isdir, path_items)):
        if name in item:
            list_dirs.append(item)
    return list_dirs

#https://stackoverflow.com/questions/229186/os-walk-without-digging-into-directories-below
def walklevel(some_dir, level=1):
    some_dir = some_dir.rstrip(os.path.sep)
    assert os.path.isdir(some_dir)
    num_sep = some_dir.count(os.path.sep)
    for root, dirs, files in os.walk(some_dir):
        yield root, dirs, files
        num_sep_this = root.count(os.path.sep)
        if num_sep + level <= num_sep_this:
            del dirs[:]

def poll_ebic(beamlines, years):
    active_sessions=[]
    mtime=False
    current_year=str(datetime.now().year)
    current_date=datetime.now()
    print(current_date)
    format = "%a %b %d %H:%M:%S %Y"
    for beamline in beamlines:
        for year in years:
            beamline_path = '/dls/{beamline}/data/{year}/'.format(beamline=beamline, year=year)
            for emsession in os.listdir(beamline_path):
                text='Running'
                session_path= beamline_path+emsession

                session_raw_path = beamline_path + emsession + '/raw/' # this should add support for sub-directories called raw (for bag sessions)
                emsession_active=False
                #session is active if raw folder last modified after 9 am today.
                if os.path.exists(session_raw_path):
                    raw_dirs = search_for_dir(session_path, 'raw')
                    for raw_dir in raw_dirs:
                        for gridsquare in os.listdir(raw_dir):
                            gridsquare_raw_path=session_raw_path + gridsquare
                            if not os.path.isdir(gridsquare_raw_path): break
                            mtime=os.path.getmtime(gridsquare_raw_path)
                            dtime=datetime.strptime(time.ctime(mtime),format)
                            if dtime.date()==current_date.date():
                                emsession_active=True
                    if emsession_active:
                        micrograph_list = poll_dir(session_raw_path, '*.mrc')
                        latest_file_ctime = time.ctime(max(ctime for (filename, ctime) in micrograph_list))
                        now_ctime = datetime.ctime(datetime.now())
                        # calculate time difference between now and the time of the latest file write
                        delta_time = time_delta(now_ctime, format, latest_file_ctime, format)
                        if (delta_time/60) > 15: text='Alert!'
                        identify_epu_folder(session_path)
                        print(beamline, emsession, str(dtime), len(micrograph_list),(delta_time/60), text)
                        active_sessions.append(emsession)
                else:
                    pass

    return active_sessions

def identify_epu_folder(emsession_path):
    for item in os.listdir(emsession_path):
        item_path = os.path.join(emsession_path, item)
        for regex in software_folder_regex.items():
            if os.path.isdir(item_path) and re.match(regex[1], item, flags=0):
                epu_folder = item_path
                if verify_epu_folder(item_path):
                    print('Identified EPU folder: {}'.format(epu_folder))

def verify_epu_folder(path):
    folder_items= os.listdir(path)
    if 'EpuSession.dm' in folder_items: return True
    #print(folder_items)

def most_recent_file(raw_movie_list):
    mlist_ctime_sorted = sorted(raw_movie_list, key=lambda l: l[1], reverse=False)
    latest_file_ctime = time.ctime(max(ctime for (filename, ctime) in raw_movie_list))


