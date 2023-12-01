from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import osgeo.gdal
from osgeo import gdal
from osgeo import osr


def tiles(canvas_shape: list[int, int], target: int = 1024) -> list[int]:
    """
    Brute force algorithm to determine the most efficient tiling method for a given canvas
    If anyone can figure out a prettier one please let me know - is actually harder then you'd think!
    """
    best_case = (canvas_shape[0] * canvas_shape[1]) / float(target ** 2)

    # Handle the trivial cases first
    if canvas_shape[0] <= target:
        return [1, math.ceil(best_case)]

    if canvas_shape[1] <= target:
        return [math.ceil(best_case), 1]

    r = [float(x) / target for x in canvas_shape]

    # Brute force the 4 methods
    a_up = [math.ceil(x) for x in r]
    b_up = [math.ceil(best_case / x) for x in a_up]

    a_down = [math.floor(x) for x in r]
    b_down = [math.ceil(best_case / x) for x in a_down]

    results = []
    for i in range(2):
        results.append((a_up[i], b_up[i], a_up[i] * b_up[i]))
        results.append((a_down[i], b_down[i], a_down[i] * b_down[i]))

    results.sort(key=lambda x: x[2])
    return [int(x) for x in results[0][0:2]]


def transform(x: int, y: int, geotransform: tuple[int]) -> tuple[int, int]:
    xt = geotransform[0] + x * geotransform[1] + y * geotransform[2]
    yt = geotransform[3] + x * geotransform[4] + y * geotransform[5]

    return xt, yt


def create_tile(img: osgeo.gdal.Dataset,
                filename: str,
                offset: tuple[int, int],
                size: list[int],
                quality: int = 75) -> dict[str, int]:
    """
    Create a jpeg of the given area and return the bounds.
    """
    mem_drv = gdal.GetDriverByName('MEM')
    mem_ds = mem_drv.Create('', size[0], size[1], img.RasterCount)
    bands = range(1, img.RasterCount + 1)

    # TODO: consider this instead https://rasterio.readthedocs.io/en/latest/
    data = img.ReadRaster(offset[0], offset[1], size[0], size[1], size[0], size[1], band_list=bands)
    mem_ds.WriteRaster(0, 0, size[0], size[1], data, band_list=bands)
    # Error comes because we go out of bounds of image?

    # Save tiles as jpeg
    jpeg_drv = gdal.GetDriverByName('JPEG')
    jpeg_drv.CreateCopy(filename, mem_ds, strict=0, options=["QUALITY={0}".format(quality)])

    geotransform = img.GetGeoTransform()

    if geotransform[2] != 0 or geotransform[4] != 0:
        raise Exception('Source projection incompatible, transform contains rotation')
    else:
        nw = transform(offset[0], offset[1], geotransform)
        se = transform(offset[0] + size[0], offset[1] + size[1], geotransform)

    result = {
        'north': nw[1],
        'east': se[0],
        'south': se[1],
        'west': nw[0],
    }

    return result


def create_kml(source: str | Path,
               filename: str | Path,
               directory: str | Path,
               tile_size: int = 1024,
               border: int = 0,
               name: str = None,
               order: int = 20,
               exclude: list[str] = None,
               quality: int = 75) -> None:
    """
    Create a kml file and associated images for the given georeferenced image 
    """

    source, filename, directory = Path(source), Path(filename), Path(directory)

    if exclude is None:
        exclude = []

    img = gdal.Open(str(source))
    if img is None:
        raise (AttributeError('Not a valid georeferenced image:', source))
    projection = img.GetProjection()
    logging.info(projection)

    # https://gdal.org/user/raster_data_model.html#raster-data-model
    srs = osr.SpatialReference(wkt=projection)
    authority = (srs.GetAttrValue('AUTHORITY', 0), srs.GetAttrValue('AUTHORITY', 1))
    logging.debug(authority)

    if authority != ('EPSG', '4326'):
        # https://gdal.org/tutorials/osr_api_tut.html#coordinate-transformation
        # ct = osr.CoordinateTransformation()
        errmsg = f'Input file is not in standard CRS. Should be EPSG 4326 but is {authority[0]} {authority[1]}'
        logging.error(errmsg)
        raise NotImplementedError(errmsg)

    img_size = [img.RasterXSize, img.RasterYSize]
    logging.debug(f'Image size: {img_size}')
    cropped_size = [x - border * 2 for x in img_size]

    base, ext = source.stem, source.suffix

    if not name:
        name = base
    path = directory.relative_to(filename.parent)

    tile_layout = tiles(cropped_size, tile_size)

    tile_sizes = [int(math.floor(x)) for x in [cropped_size[0] / tile_layout[0], cropped_size[1] / tile_layout[1]]]
    logging.debug(f'Using tile layout {tile_layout} -> {tile_sizes}')

    bob = open(filename, 'w')

    bob.write(f"""<?xml version="1.0" encoding="UTF-8"?>
             <kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" 
             xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">
               <Folder>
                 <name>{name}</name>
             """)

    for t_y in range(tile_layout[1]):
        for t_x in range(tile_layout[0]):
            tile = f'{t_y},{t_x}'
            logging.debug(tile)
            if tile in exclude:
                logging.debug(f"Excluding tile {tile}")
            else:
                src_corner = (border + t_x * tile_sizes[0], border + t_y * tile_sizes[1])
                src_size = [tile_sizes[0], tile_sizes[1]]
                if src_corner[0] + tile_sizes[0] > img_size[0] - border:
                    src_size[0] = int(tile_sizes[0])

                if src_corner[1] + tile_sizes[1] > img_size[1] - border:
                    src_size[1] = int(tile_sizes[1])

                outfile = f'{base}_{t_x:d}_{t_y:d}.jpg'
                outpath = f'{directory}/{outfile}'

                if src_corner[0] + src_size[0] > img_size[0]:
                    logging.error('Pixel range outside image data!')
                    logging.error(f'Image width {img_size[0]}, trying to get at x={src_corner[0] + src_size[0]}')
                bounds = create_tile(img, outpath, src_corner, src_size, quality)

                bob.write(f"""    <GroundOverlay>
                <name>{outfile}</name>
                <color>ffffffff</color>
                <drawOrder>{order}</drawOrder>
                <Icon>
                    <href>{path}/{outfile}</href>
                    <viewBoundScale>0.75</viewBoundScale>
                </Icon>
                <LatLonBox>""")

                bob.write(f"""<north>{bounds['north']}</north>
                                <south>{bounds['south']}</south>
                                <east>{bounds['east']}</east>
                                <west>{bounds['west']}</west>
                                <rotation>0</rotation>
                """)
                bob.write("""        </LatLonBox>
            </GroundOverlay>
    """)

    bob.write("""  </Folder>
    </kml>
    """)

    bob.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Convert a georeferenced TIFF file to KML file')

    parser.add_argument('src_file', metavar='src_file', type=str, help='source file')
    parser.add_argument('dst_file', metavar='dst_file', type=str, help='destination file')

    parser.add_argument('-d', '--dir', dest='directory', help='Where to create jpeg tiles')
    parser.add_argument('-c', '--crop', default=0, dest='border', type=int, help='Crop border')
    parser.add_argument('-n', '--name', dest='name', help='KML folder name for output')
    parser.add_argument('-o', '--draw-order', dest='order', type=int, default=20, help='KML draw order')
    parser.add_argument('-t', '--tile-size', dest='tile_size', default=1024, type=int, help='Max tile size [1024]')
    parser.add_argument('-q', '--quality', dest='quality', default=75, type=int, help='JPEG quality [75]')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    source_file, destination_file = Path(args.src_file), Path(args.dst_file)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # validate a few options
    if not source_file.exists():
        parser.error('unable to file src_file')

    # set the default folder for jpegs
    if not args.directory:
        directory = destination_file.with_suffix('.files')
    else:
        directory = Path(args.directory)

    directory.mkdir(exist_ok=True)

    logging.info(f'Writing jpegs to {args.directory}')

    # load the exclude file
    exclude_file = source_file.with_suffix('.exclude')
    exclude = []
    if exclude_file.exists():
        logging.debug(f"Using exclude file {exclude_file}")
        for line in open(exclude_file):
            exclude.append(line.rstrip())
        logging.debug(exclude)

    create_kml(source_file, destination_file, directory,
               tile_size=args.tile_size,
               border=args.border,
               name=args.name,
               order=args.order,
               exclude=exclude,
               quality=args.quality)
