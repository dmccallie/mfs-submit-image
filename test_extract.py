import os
import sys
from  iptcinfo3 import IPTCInfo

# print("sys arg1:", sys.argv[1])
# filename = os.path.basename(sys.argv[1])
filename = "/mnt/d/Dropbox/McCallieFamilyStories/Zoomfest-Feb2025/Zoom Feb 16/allison IMG_2286_xmp.jpg"

info = IPTCInfo(filename)
# print("info:", info)
for k, v in info._data.items():
	print("key:", k, "value:", v)

print("Title:", info['object name'])
print("Caption/Abstract:", info['caption/abstract'])
print("Keywords:", info['keywords'])
print("Byline:", info['by-line'])
print("Credit:", info['credit'])
print("Source:", info['source'])	

# now set some values
# 'object name' shows up as Title in PS, presumably LR
info['object name'] = "New Title via object name field"

# shows up as Headline in PS, presumably LR
info['headline'] = "New Headline via headline field"

# info['title'] = DOES NOT WORK "New Title using title field"
# caption/abstract shows up in Description field in PS, presumably LR 
info['caption/abstract'] = "This is a new caption/abstract set via caption/abstract field."

# info['Description'] = "This is a new description set via python  Description field."

# keywords works
info['keywords'] = ['keyword1', 'keyword2', 'keyword3']

# don't use this one
info['by-line'] = "John Doe"

# works
info['source'] = "John Doe Studio"	

# use save as to write changes to a new file
new_filename = "/mnt/d/Dropbox/McCallieFamilyStories/Zoomfest-Feb2025/Zoom Feb 16/allison IMG_2286_xmp_modified.jpg"
info.save_as(new_filename)
print(f"Modified IPTC data saved to {new_filename}")	


