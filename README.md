# Simple tool to submit photos for photo project at mccalliefamilystories Humhub site
## About
A simple tool to allow family members to upload and annotate photographs for consideration for use in the photo archive project.  

Each photo expects to be annotated with:
- a simple "title" (which will become part of the photos eventual file name)
- a free text "description" which should contain as much contextual information as is known, including who is in the photograph and (approximately) when it was taken. 
- source - the abbreviated name of who submitted this photograph.

These fields will be embedded into the image's metadata using `ExifTool`.  These fields are mapped to a mixture of XMP and IPTC fields, designed for easy access in Photoshop or other editor tools.  When in doubt, use `ExifTool` on the command line to read the embedded data.

The photos are stored on S3, using the submitter as the first part of the name, a sanitized version of the 'title' as the second part, plus a random four digit number, plus the extension. For example
```
mfs-photo-submissions/JBM/Dr-James-Fowle-with-wedding-party-9532.jpg
```
When it's time to actually load the images into Humhub, the best process is probably to use S3 web console to download the images locally, where they can be edited if necesary and then uploaded into Humhub. There is no direct route to HH being planned.

## Config stuff
- in the `.env` file, be sure to set up AWS S3 keys, as well as to add a password for the invited users. No user name, just a shared password.
- in the app code itself, be sure to add abbreviated names to `SUBMITTER_NAMES` for each person we expect to submit photos

## Caddyfile setup
Be sure to add this to the master Caddyfile. Note that Route53 needs to forward `*.mccalliefamilystories.com` to the A record that points to the VPS's IP address

```
submit.mccalliefamilystories.com {
    reverse_proxy http://mfs-submit-image-app:5001 {
        header_up X-Forwarded-Port 443
        header_up X-Forwarded-Proto {scheme}
        header_up X-Forwarded-Host {host}
    }
}
```

## Docker and Compose
Current plan is to use this repo (mfs-submit-image) to keep the code for the app, and then inside the mccalliefamilystories monorepository we'll have the compose file that pulls from this repo into the VPS for a local build, using python 3.12 and related libraries. Be sure that that `docker network create web` has been set up for all these containers to share the same caddy instance.

## Deployment
- docker compose pull (for other services that use images)
- docker compose build --no-cache mfs-submit-image (or just docker compose up -d --build mfs-submit-image)
- docker compose up -d
- docker compose logs -f mfs-submit-image