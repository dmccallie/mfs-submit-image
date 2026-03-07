# using pyexiftool to write some fields to be checked in PS and LR
import os
import sys
from exiftool import ExifTool, ExifToolHelper
filename = "./data/images/sjm-portrait.jpg"

import os

from exiftool import ExifToolHelper
from datetime import datetime
from typing import List, Optional


def embed_photo_metadata_with_xmp(
    image_path: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    creator: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    circa_date_created: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    credit: Optional[str] = None,
    source: Optional[str] = None,
):
    """
    Embed archival metadata into a JPEG using XMP fields.

    Parameters
    ----------
    image_path : str
        Path to the JPEG image.

    title : str
        Title of the image.
        Shows in Photoshop as Basic: "Title" 

    description : str
        Caption or description.
        Shows in Photoshop as Basic: "Description"

    creator : str
        Photographer or archive creator.
        Shows in Photoshop Basic: "Author"
        Shows in PS IPTC as "Creator"

    keywords : list[str]
        Searchable keywords.
        Shows in Photoshop Basic: "Keywords" (semicolon-separated)

    circa_date_created : str
        Historical or estimated date of photo (as text).
        Does not appear in Photoshop's XMP viewer so we shouldn't rely on it.
        Maybe store this info in the Description field by convention?

    city/state/country : str
        Location metadata.
        Shows in PS IPTC and PS Origin as "City", "State/Province", and "Country"

    credit : str
        Archive credit line.
        Shows in PS Origin and IPTC as "Credit Line"

    source : str
        Provenance or submission source.
        Shows in PS Origin and IPTC as "Source"
    """

    tags = {}

    if title:
        tags["XMP-dc:Title"] = title
        tags['XMP-photoshop:Headline'] = title

    if description:
        tags["XMP-dc:Description"] = description

    if creator:
        tags["XMP-dc:Creator"] = creator

    if keywords:
        tags["XMP-dc:Subject"] = keywords

    if circa_date_created:
        # this one doesn't work?
        # tags["XMP-photoshop:DateCreated"] = date_created
        # CircaDateCreated doesn't show in PS XMP viewer.
        tags["XMP-iptcExt:CircaDateCreated"] = circa_date_created

    if city:
        tags["XMP-photoshop:City"] = city

    if state:
        tags["XMP-photoshop:State"] = state

    if country:
        tags["XMP-photoshop:Country"] = country

    if credit:
        tags["XMP-photoshop:Credit"] = credit

    if source:
        tags["XMP-photoshop:Source"] = source
        tags["XMP-iptcCore:Source"] = source

    if not tags:
        return

    with ExifToolHelper() as et:
        et.set_tags(
            image_path,
            tags,
            params=["-overwrite_original"],
        )

print("filename exists:", os.path.exists(filename))

# dump existing metadata
with ExifToolHelper() as et:
    for d in et.get_metadata(filename):
        for k, v in d.items():
            print(f"Dict: {k} = {v}")

# test new function
embed_photo_metadata_with_xmp(
    filename,
    title="Test Title",
    description="Test Description",
    creator="Test Creator",             
    keywords=["keyword1", "keyword2"],
    circa_date_created="test circa 1952",
    city="Test City",
    state="Test State",
    country="Test Country",
    credit="Test Credit",
    source="Test Source",
)

# dump metadata again to verify changes
with ExifToolHelper() as et:
    for d in et.get_metadata(filename):
        for k, v in d.items():
            print(f"Dict: {k} = {v}")

