import glob, os, time, sys, fnmatch, subprocess, numpy, re, httplib, urllib # mrcfile
import matplotlib.pyplot as plt
import logging

import session_func_lite as session_func

from PIL import Image
from datetime import datetime
from string import Template
from shutil import copyfile

poll_interval=7.5*60 # minutes multiplied by seconds per minute
update_interval=29*60 # minutes multiplied by seconds per minute
warning_delta=15*60 # minutes multiplied by seconds per minute

# session parameters
beamline = 'm0X'
em_session = 'emXXXXX-XX'
session_name = 'User1'

epu_folder=None#'/dls/m07/data/2018/em14856-38/supervisor_20180713_EPU2'

session_start='Aug 08 09:00:00 2018'
session_end ='Aug 10 09:00:00 2018'
session_type='SPcryoEM_EPU' # 'cryoET_TOMO4'

re_dict={'cryoET_EPU': '(.*)_(\d{3})[[](.*)[]]-(\d{5})-(\d{4}).mrc', 'SPcryoEM_EPU':'FoilHole_(\d{8})_Data_(\d{8})_(\d{8})_(\d{8})_(\d{4}).mrc' }
raw_folder = 'raw'

reg_ex_epu_folder='supervisor_\d{8}.*_EPU' # this needs to be confirmed.
reg_ex_tomo4_folder='supervisor_\d{8}.*_TOMO4' # this needs to be confirmed.
reg_ex_epu_micrograph= '.*(GridSquare_\d*).*((FoilHole_\d*_Data_\d*_(\d*)_(\d*))_(\d*))_Fractions.mrc' #''(FoilHole_\d{7}_Data_\d{7}_\d{7}_(\d{8})_(\d{4})-(\d{5})).mrc'
# reg-ex falcon 3 linear (FoilHole_\d*_Data_\d*_(\d*)_(\d*))_(\d*).mrc
# reg-ex k2 linear '.*(GridSquare_\d*).*(FoilHole_\d*_Data_\d*_\d*_(\d*)_(\d*))-(\d*).mrc'

# script parameters
test=False
regular_updates=True
use_pushover=True
use_email=True
produce_micrograph_montage=True
poll_epu_folder=False

monitoring=True
update_counter=0
iteration=0
micrographcount_list=[]
update_time_last=None
update_time_now=None

email_ad=['a@b.ac.uk']

pushover_apptoken='' # this is created on the push over web interface.
pushover_userkey=''

# create base variables
year=str(datetime.now().year)
format = "%a %b %d %H:%M:%S %Y"
session_end_format= "%b %d %H:%M:%S %Y"
session_end_time=datetime.strptime(session_end,session_end_format)
session_start_time=datetime.strptime(session_start,session_end_format)
# files identified in the raw_path will be compared with files found in the epu path.
emsession_path= '/dls/' + beamline + '/data/' + year + '/' + em_session + '/'
#epu_folder='EPU_' + em_session + '_' + '{}{:02d}{:02d}'.format(session_end_time.year, session_start_time.month, session_start_time.day)

# poll session folder to identify EPU folder

# identify EPU folder path

num_folders=0
if epu_folder == None:
    for item in os.listdir(emsession_path):
        item_path=os.path.join(emsession_path, item)
        if os.path.isdir(item_path) and re.match(reg_ex_epu_folder, item,flags=0):
            epu_folder=item_path
            num_folders+=1
            print('Identified EPU folder: {}'.format(epu_folder))
        else:
            print('WARNING: no EPU folder has been found. Please check, and specify if necessary.')

    if epu_folder==None or num_folders>1:
        print('No EPU folder identified, disabling associated functions')
        poll_epu_folder=False
        parse_xml=False

movie_path=emsession_path + raw_folder + '/'
emsession_log_folder= '/scratch/emsession_log'
current_log_folder= emsession_log_folder+'/'+ beamline + '_' + em_session
output_log=current_log_folder+'/'+'rate.log'
print('Output log: {}'.format(output_log))
gctf_folder=current_log_folder+'/gCTF'
motioncor2_folder=current_log_folder+'/motioncor2'
cmds=[]

# setup logging directory structure
if os.path.exists(emsession_log_folder)==False: # prepare folder structure
  os.mkdir(emsession_log_folder)

if os.path.exists(current_log_folder)==False:
  os.mkdir(current_log_folder)

if os.path.exists(motioncor2_folder)==False:
  os.mkdir(motioncor2_folder)

while monitoring:
  iteration += 1
  print('Monitoring folder:', movie_path)
  print('Starting monitoring for EM session: {}. This is iteration {}.'.format(em_session, iteration))

  poll_start_ctime=datetime.ctime(datetime.now())
  delta_seconds_session=session_func.time_delta(poll_start_ctime, format, session_end, session_end_format)

  # check that the session has not expired.
  if delta_seconds_session>1: # the current time is after the specified end time...
    print('Session expired, exiting...')
    message_body = '{} has now concluded. Updates discontinued.'.format(em_session)
    session_func.pushover_message(pushover_apptoken, pushover_userkey, message_body, -1)
    # poll entire session?
    # mrc_list, mrc_raw_list = session_func.poll_emsession(emsession_path) # mrc_raw_list, mrc_list, xml_list,
    sys.exit()
  elif delta_seconds_session<0:
    hours_remaining=abs(delta_seconds_session)/60**2
    print('{0:.2f} hours remaining'.format(hours_remaining))
  # poll the raw folder for mrc files

  raw_movie_list=[]
  raw_movie_list = session_func.poll_dir(movie_path, '*.mrc')
  poll_end_ctime = datetime.ctime(datetime.now())
  poll_time = session_func.time_delta(poll_end_ctime, format, poll_start_ctime, format)
  num_micrographs=len(raw_movie_list)
  print('Polling time of {} seconds, {} micrographs identified'.format(poll_time, num_micrographs))
  mlist_ctime_sorted=sorted(raw_movie_list,key=lambda l:l[1], reverse=False)

  # take movie_list and create time delta for each file.
  micrographcount_list.append([poll_end_ctime, num_micrographs])

  try:
    acquisition_rate_log=open(output_log,'a')
    write_string=' '.join([iteration,poll_end_ctime, num_micrographs, poll_time])
    print(write_string)
    acquisition_rate_log.write(write_string)
    acquisition_rate_log.close()
  except Exception:
      print('WARNING: Problem writing acquisition rate output log.')
  try:
    latest_file_ctime =  time.ctime(max(ctime for (filename, ctime) in raw_movie_list))
    now_ctime = datetime.ctime(datetime.now())
    # calculate time difference between now and the time of the latest file write, if there is a problem e-mail people to check the microscope.
    delta_time=session_func.time_delta(now_ctime, format, latest_file_ctime, format)
  except Exception:
      print('Problem determining latest file creation time')

  if iteration>1:
    try:
        delta_micrographs=micrographcount_list[-1][1]-micrographcount_list[-2][1]
    except Exception, error:
        delta_micrographs=0
        print('Exception: micrograph count list broken.')
  elif iteration==1:
      delta_micrographs=10
      print('This is the first iteration...')

  print(delta_micrographs, ' microgaphs written! (DEBUG)')

  if delta_micrographs != 0:
      print('{} new micrographs identified in iteration {}'.format(delta_micrographs, iteration))
      if iteration==1:
          index=num_micrographs-10
          print(index)
      else:
          index=len(mlist_ctime_sorted)-delta_micrographs
          print(index)

      print(index) # create list of micrographs recorded over last period
      recent_mlist=mlist_ctime_sorted[index:]

      step_size=delta_micrographs/num_datapoints

      if step_size <1: step_size=1

      print('Using step size of {}'.format(step_size))
      max_index=len(recent_mlist)+1

      sliced_mlist=recent_mlist[slice(0,max_index,step_size)]

      EPU_file_template = '{epupath}/Images-Disc{disc}/{gridsquare_id}/Data/{micrograph_id}{extension}'
      item_dict_list = []

      for item in sliced_mlist:
          item_dict={}
          print(item)
          micrograph_regex_groups = re.match(reg_ex_epu_micrograph, item[0], flags=0).groups()
          gridsquare_id=micrograph_regex_groups[0]
          micrograph_id=micrograph_regex_groups[1]
          epu_jpg = EPU_file_template.format(epupath=epu_folder,disc='1', gridsquare_id=gridsquare_id, micrograph_id=micrograph_id, extension='.jpg')

          jpg_list.append(epu_jpg)
          item_dict_list.append(item_dict)

  elif delta_micrographs=='unknown' and num_micrographs>1:
      index=len(mlist_ctime_sorted)-1
      recent_mlist=mlist_ctime_sorted[index:]

  if produce_micrograph_montage:
      # produce combined jpg
      try:
        tiled_thumbs = session_func.tile_jpegs(jpg_list)
        thumbs_filename=current_log_folder + '/montage_it{:04d}.jpg'.format(iteration)
        tiled_thumbs.save(thumbs_filename)
      except Exception, error:
        print(error)

  if regular_updates: # compile e-mail body
      update_time_now = datetime.ctime(datetime.now())

      send_update=False
      if iteration==1:
          send_update=True
          update_time_last = update_time_now
      elif iteration > 1:
          delta_update_time = session_func.time_delta(update_time_now, format, update_time_last, format)
          print('Time since last update: {} seconds'.format(delta_update_time))
          if delta_update_time >= update_interval:
            send_update=True

      else:
          send_update=False
          print('Not an update iteration')
      if session_type=='SPcryoEM_EPU':
            update_period_hrs=(float(poll_interval/60**2))
            estimated_hourly=delta_micrographs*(1/update_period_hrs)
            mail_filename = current_log_folder + '/mail_it{:04d}.txt'.format(iteration)
            message_subject='{}_{} ({}) has acquired {} ({} in {} hrs, est. {} per hour). {} hrs remaining. [EM{:03d}]'.format(beamline, em_session, session_name, num_micrographs, delta_micrographs, update_period_hrs, estimated_hourly, round(hours_remaining,2), iteration)

            if send_update:
                try:
                    session_func.pushover_message(pushover_apptoken, pushover_userkey, message_subject, -1)
                except Exception, error:
                    print(error)
            # report XML parameters, and gCTF output
            mail_body='Hello, an update on {} {} which is a {} session. \n\n'.format(beamline, em_session, session_type)
            mail_body='{} micrographs have been written since the last update. \n\n'.format(num_micrographs)
            mail_body+='A micrograph was last written {:0.1f} seconds ago \n\n'.format(delta_time)
            mail_body+='The raw folder poll time was {} seconds \n\n'.format(poll_time)
            #mail_body+='The session is expected to continue for another {} hours, and collect another {} micrographs, making for {} in total \n'.format(remaining_time, projected_remaining, projected_total)

            micrograph_details=''
            # retrieve values for monitored keys

            mail_body+=micrograph_details
            attachments =[]
            if produce_micrograph_montage:
                attachments.append(thumbs_filename)

            for mail_address in email_ad:
                if send_update:
                  session_func.mutt_mail(mail_address, message_subject, mail_body, attachments, mail_filename)
      elif session_type=='cryoET_TOMO4':
          pass

  delta_time_min = round(delta_time / 60, 1)

  if delta_time>warning_delta or send_alarm==True:
    msg_body_alert="{} alert! {} minutes since last acquisition".format(em_session,delta_time_min)
    if os.path.exists('./silence.txt'): break
    for i in range(0,4):
        session_func.pushover_message(pushover_apptoken, pushover_userkey, msg_body_alert, 1)
        time.sleep(30)

    for mail_address in email_ad:
      session_func.send_message(mail_address, ('{}_{} is in trouble!'.format(beamline,em_session)), msg_body_alert)

  if send_update: update_time_last=update_time_now
  print('A micrograph was last written {:0.1f} minutes ago. \nSleeping for an interval of {} seconds'.format(delta_time_min, poll_interval))

  update_counter+=1
  iteration+=1
  time.sleep(poll_interval)





