import argparse
import logging
import os.path
import re
import zipfile

from xml.dom.minidom import parse


def htc(m):
    return chr(int(m.group(1), 16))


def urldecode(url):
    rex = re.compile('%([0-9a-hA-H][0-9a-hA-H])', re.M)
    return rex.sub(htc, url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Convert KML file to KMZ (Garmin CustomMap) file'
    )
    parser.add_argument('src_file', metavar='src_file', type=str, help='Source file')

    parser.add_argument('-o', '--outfile', dest="outfile", metavar="FILE", help="Write output to FILE")
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # check for KML
    if args.src_file is None:
        parser.error('Path to KML file is required')

    if not os.path.exists(args.src_file):
        parser.error(f'Unable to find KML: {args.src_file}')

    if not args.outfile:
        args.outfile = os.path.basename(args.src_file)[:-4] + '.kmz'
    logging.info("Output to", args.outfile)

    # create the output zip file
    zipped = zipfile.ZipFile(args.outfile, 'w', zipfile.ZIP_DEFLATED)

    # read the source xml
    kml = parse(args.src_file)
    nodes = kml.getElementsByTagName('href')

    base = os.path.dirname(args.src_file)

    for node in nodes:
        href = node.firstChild

        img = urldecode(href.nodeValue).replace('file:///', '')
        if not os.path.exists(img):
            img = base + '/' + img

        if not os.path.exists(img):
            parser.error(f'Unable to find image: {img}')

        # add the image
        filename = f'files/{os.path.basename(img)}'
        logging.debug(f"Storing {img} as {filename}")
        zipped.write(img, filename, zipfile.ZIP_STORED)

        # modify the xml to point to the correct image
        href.nodeValue = filename

    logging.debug("Storing KML as doc.kml")
    zipped.writestr('doc.kml', kml.toxml("UTF-8"))

    zipped.close()
    logging.info("Finished")
