import sys
from utils import random_utils
import numpy as np
import cv2
import localization
from scipy.spatial import Delaunay
from PIL import Image, ImageDraw, ImageFont

def channel_hist_match(source, template, mask=None):
    # Code borrowed from:
    # https://stackoverflow.com/questions/32655686/histogram-matching-of-two-images-in-python-2-x
    masked_source = source
    masked_template = template

    if mask is not None:
        masked_source = source * mask
        masked_template = template * mask

    oldshape = source.shape
    source = source.ravel()
    template = template.ravel()
    masked_source = masked_source.ravel()
    masked_template = masked_template.ravel()
    s_values, bin_idx, s_counts = np.unique(source, return_inverse=True,
                                            return_counts=True)
    t_values, t_counts = np.unique(template, return_counts=True)
    ms_values, mbin_idx, ms_counts = np.unique(source, return_inverse=True,
                                            return_counts=True)
    mt_values, mt_counts = np.unique(template, return_counts=True)

    s_quantiles = np.cumsum(s_counts).astype(np.float64)
    s_quantiles /= s_quantiles[-1]
    t_quantiles = np.cumsum(t_counts).astype(np.float64)
    t_quantiles /= t_quantiles[-1]
    interp_t_values = np.interp(s_quantiles, t_quantiles, t_values)

    return interp_t_values[bin_idx].reshape(oldshape)    

def color_hist_match(src_im, tar_im, mask=None):
    h,w,c = src_im.shape
    matched_R = channel_hist_match(src_im[:,:,0], tar_im[:,:,0], mask)
    matched_G = channel_hist_match(src_im[:,:,1], tar_im[:,:,1], mask)
    matched_B = channel_hist_match(src_im[:,:,2], tar_im[:,:,2], mask)
    
    to_stack = (matched_R, matched_G, matched_B)
    for i in range(3, c):
        to_stack += ( src_im[:,:,i],)
    
    
    matched = np.stack(to_stack, axis=-1).astype(src_im.dtype)
    return matched
    

pil_fonts = {}
def _get_pil_font (font, size):
    global pil_fonts
    try:
        font_str_id = '%s_%d' % (font, size)
        if font_str_id not in pil_fonts.keys():
            pil_fonts[font_str_id] = ImageFont.truetype(font + ".ttf", size=size, encoding="unic")
        pil_font = pil_fonts[font_str_id]
        return pil_font    
    except:
        return ImageFont.load_default()
                
def get_text_image( shape, text, color=(1,1,1), border=0.2, font=None):
    try:     
        size = shape[1]
        pil_font = _get_pil_font( localization.get_default_ttf_font_name() , size)
        text_width, text_height = pil_font.getsize(text)
        
        canvas = Image.new('RGB', shape[0:2], (0,0,0) )
        draw = ImageDraw.Draw(canvas)
        offset = ( 0, 0)
        draw.text(offset, text, font=pil_font, fill=tuple((np.array(color)*255).astype(np.int)) )
        
        result = np.asarray(canvas) / 255
        if shape[2] != 3:        
            result = np.concatenate ( (result, np.ones ( (shape[1],) + (shape[0],) + (shape[2]-3,)) ), axis=2 )

        return result
    except:    
        return np.zeros ( (shape[1], shape[0], shape[2]), dtype=np.float32 )
    
def draw_text( image, rect, text, color=(1,1,1), border=0.2, font=None):
    h,w,c = image.shape
 
    l,t,r,b = rect
    l = np.clip (l, 0, w-1)
    r = np.clip (r, 0, w-1)
    t = np.clip (t, 0, h-1)
    b = np.clip (b, 0, h-1)
    
    image[t:b, l:r] += get_text_image (  (r-l,b-t,c) , text, color, border, font )
                
def draw_text_lines (image, rect, text_lines, color=(1,1,1), border=0.2, font=None):
    text_lines_len = len(text_lines)
    if text_lines_len == 0:
        return
        
    l,t,r,b = rect
    h = b-t
    h_per_line = h // text_lines_len
    
    for i in range(0, text_lines_len):
        draw_text (image, (l, i*h_per_line, r, (i+1)*h_per_line), text_lines[i], color, border, font)
        
def get_draw_text_lines ( image, rect, text_lines, color=(1,1,1), border=0.2, font=None):
    image = np.zeros ( image.shape, dtype=np.float )
    draw_text_lines ( image, rect, text_lines, color, border, font)
    return image
        
  
def draw_polygon (image, points, color, thickness = 1):
    points_len = len(points)
    for i in range (0, points_len):
        p0 = tuple( points[i] )
        p1 = tuple( points[ (i+1) % points_len] )
        cv2.line (image, p0, p1, color, thickness=thickness)
        
def draw_rect(image, rect, color, thickness=1):
    l,t,r,b = rect
    draw_polygon (image, [ (l,t), (r,t), (r,b), (l,b ) ], color, thickness)

def rectContains(rect, point) :
    return not (point[0] < rect[0] or point[0] >= rect[2] or point[1] < rect[1] or point[1] >= rect[3])

def applyAffineTransform(src, srcTri, dstTri, size) :
    warpMat = cv2.getAffineTransform( np.float32(srcTri), np.float32(dstTri) )
    return cv2.warpAffine( src, warpMat, (size[0], size[1]), None, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101 )    
    
def morphTriangle(dst_img, src_img, st, dt) :                                
    (h,w,c) = dst_img.shape
    sr = np.array( cv2.boundingRect(np.float32(st)) )
    dr = np.array( cv2.boundingRect(np.float32(dt)) )
    sRect = st - sr[0:2]
    dRect = dt - dr[0:2]
    d_mask = np.zeros((dr[3], dr[2], c), dtype = np.float32)
    cv2.fillConvexPoly(d_mask, np.int32(dRect), (1.0,)*c, 8, 0);                                    
    imgRect = src_img[sr[1]:sr[1] + sr[3], sr[0]:sr[0] + sr[2]]                                    
    size = (dr[2], dr[3])                                    
    warpImage1 = applyAffineTransform(imgRect, sRect, dRect, size)                      
    dst_img[dr[1]:dr[1]+dr[3], dr[0]:dr[0]+dr[2]] = dst_img[dr[1]:dr[1]+dr[3], dr[0]:dr[0]+dr[2]]*(1-d_mask) + warpImage1 * d_mask
    
def morph_by_points (image, sp, dp):
    if sp.shape != dp.shape:
        raise ValueError ('morph_by_points() sp.shape != dp.shape')
    (h,w,c) = image.shape    

    result_image = np.zeros(image.shape, dtype = image.dtype)

    for tri in Delaunay(dp).simplices:                                    
        morphTriangle(result_image, image, sp[tri], dp[tri])
       
    return result_image
    
def equalize_and_stack_square (images, axis=1):
    max_c = max ([ 1 if len(image.shape) == 2 else image.shape[2]  for image in images ] )
    
    target_wh = 99999
    for i,image in enumerate(images):
        if len(image.shape) == 2:
            h,w = image.shape
            c = 1
        else:
            h,w,c = image.shape
        
        if h < target_wh:
            target_wh = h
    
        if w < target_wh:
            target_wh = w
            
    for i,image in enumerate(images):
        if len(image.shape) == 2:
            h,w = image.shape
            c = 1
        else:
            h,w,c = image.shape
            
        if c < max_c:
            if c == 1:
                if len(image.shape) == 2:
                    image = np.expand_dims ( image, -1 )                
                image = np.concatenate ( (image,)*max_c, -1 )
            elif c == 2: #GA
                image = np.expand_dims ( image[...,0], -1 )
                image = np.concatenate ( (image,)*max_c, -1 )                
            else:
                image = np.concatenate ( (image, np.ones((h,w,max_c - c))), -1 )

        if h != target_wh or w != target_wh:
            image = cv2.resize ( image, (target_wh, target_wh) )
            h,w,c = image.shape
                
        images[i] = image
        
    return np.concatenate ( images, axis = 1 )
    
def bgr2hsv (img):    
    return cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
def hsv2bgr (img):    
    return cv2.cvtColor(img, cv2.COLOR_HSV2BGR)
    
def bgra2hsva (img):    
    return np.concatenate ( (cv2.cvtColor(img[...,0:3], cv2.COLOR_BGR2HSV ), np.expand_dims (img[...,3], -1)), -1 )

def bgra2hsva_list (imgs):
    return [ bgra2hsva(img) for img in imgs ]
    
def hsva2bgra (img):
    return np.concatenate ( (cv2.cvtColor(img[...,0:3], cv2.COLOR_HSV2BGR ), np.expand_dims (img[...,3], -1)), -1 )

def hsva2bgra_list (imgs):
    return [ hsva2bgra(img) for img in imgs ]
    
def gen_warp_params (source, flip, rotation_range=[-10,10], scale_range=[-0.5, 0.5], tx_range=[-0.05, 0.05], ty_range=[-0.05, 0.05]  ):
    h,w,c = source.shape
    if (h != w) or (w != 64 and w != 128 and w != 256 and w != 512 and w != 1024):
        raise ValueError ('TrainingDataGenerator accepts only square power of 2 images.')
        
    rotation = np.random.uniform( rotation_range[0], rotation_range[1] )
    scale = np.random.uniform(1 +scale_range[0], 1 +scale_range[1])
    tx = np.random.uniform( tx_range[0], tx_range[1] )
    ty = np.random.uniform( ty_range[0], ty_range[1] ) 
 
    #random warp by grid
    cell_size = [ w // (2**i) for i in range(1,4) ] [ np.random.randint(3) ]
    cell_count = w // cell_size + 1
    
    grid_points = np.linspace( 0, w, cell_count)
    mapx = np.broadcast_to(grid_points, (cell_count, cell_count)).copy()
    mapy = mapx.T
    
    mapx[1:-1,1:-1] = mapx[1:-1,1:-1] + random_utils.random_normal( size=(cell_count-2, cell_count-2) )*(cell_size*0.24)
    mapy[1:-1,1:-1] = mapy[1:-1,1:-1] + random_utils.random_normal( size=(cell_count-2, cell_count-2) )*(cell_size*0.24)

    half_cell_size = cell_size // 2
    
    mapx = cv2.resize(mapx, (w+cell_size,)*2 )[half_cell_size:-half_cell_size-1,half_cell_size:-half_cell_size-1].astype(np.float32)
    mapy = cv2.resize(mapy, (w+cell_size,)*2 )[half_cell_size:-half_cell_size-1,half_cell_size:-half_cell_size-1].astype(np.float32)
    
    #random transform
    random_transform_mat = cv2.getRotationMatrix2D((w // 2, w // 2), rotation, scale)
    random_transform_mat[:, 2] += (tx*w, ty*w)
    
    params = dict()
    params['mapx'] = mapx
    params['mapy'] = mapy
    params['rmat'] = random_transform_mat
    params['w'] = w        
    params['flip'] = flip and np.random.randint(10) < 4
            
    return params
    
def warp_by_params (params, img, warp, transform, flip):
    if warp:
        img = cv2.remap(img, params['mapx'], params['mapy'], cv2.INTER_LANCZOS4 )
    if transform:
        img = cv2.warpAffine( img, params['rmat'], (params['w'], params['w']), borderMode=cv2.BORDER_CONSTANT, flags=cv2.INTER_LANCZOS4 )            
    if flip and params['flip']:
        img = img[:,::-1,:]
    return img
    
#n_colors = [0..256]
def reduce_colors (img_bgr, n_colors):
    img_rgb = (cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB) * 255.0).astype(np.uint8)
    img_rgb_pil = Image.fromarray(img_rgb)
    img_rgb_pil_p = img_rgb_pil.convert('P', palette=Image.ADAPTIVE, colors=n_colors)
    
    img_rgb_p = img_rgb_pil_p.convert('RGB')
    img_bgr = cv2.cvtColor( np.array(img_rgb_p, dtype=np.float32) / 255.0, cv2.COLOR_RGB2BGR )
    
    return img_bgr
    
    
class TFLabConverter():



    def __init__(self,):
        import gpufmkmgr
        
        self.tf_module = gpufmkmgr.import_tf()
        self.tf_session = gpufmkmgr.get_tf_session()
        
        self.bgr_input_tensor = self.tf_module.placeholder("float", [None, None, 3])
        self.lab_input_tensor = self.tf_module.placeholder("float", [None, None, 3])
        
        self.lab_output_tensor = self.rgb_to_lab(self.tf_module, self.bgr_input_tensor)        
        self.bgr_output_tensor = self.lab_to_rgb(self.tf_module, self.lab_input_tensor)
        
        
    def bgr2lab(self, bgr):    
        return self.tf_session.run(self.lab_output_tensor, feed_dict={self.bgr_input_tensor: bgr})
        
    def lab2bgr(self, lab):    
        return self.tf_session.run(self.bgr_output_tensor, feed_dict={self.lab_input_tensor: lab})    
        
    def rgb_to_lab(self, tf, rgb_input):
        with tf.name_scope("rgb_to_lab"):
            srgb_pixels = tf.reshape(rgb_input, [-1, 3])

            with tf.name_scope("srgb_to_xyz"):
                linear_mask = tf.cast(srgb_pixels <= 0.04045, dtype=tf.float32)
                exponential_mask = tf.cast(srgb_pixels > 0.04045, dtype=tf.float32)
                rgb_pixels = (srgb_pixels / 12.92 * linear_mask) + (((srgb_pixels + 0.055) / 1.055) ** 2.4) * exponential_mask
                rgb_to_xyz = tf.constant([
                    #    X        Y          Z
                    [0.412453, 0.212671, 0.019334], # R
                    [0.357580, 0.715160, 0.119193], # G
                    [0.180423, 0.072169, 0.950227], # B
                ])
                xyz_pixels = tf.matmul(rgb_pixels, rgb_to_xyz)

            # https://en.wikipedia.org/wiki/Lab_color_space#CIELAB-CIEXYZ_conversions
            with tf.name_scope("xyz_to_cielab"):
                # convert to fx = f(X/Xn), fy = f(Y/Yn), fz = f(Z/Zn)

                # normalize for D65 white point
                xyz_normalized_pixels = tf.multiply(xyz_pixels, [1/0.950456, 1.0, 1/1.088754])

                epsilon = 6/29
                linear_mask = tf.cast(xyz_normalized_pixels <= (epsilon**3), dtype=tf.float32)
                exponential_mask = tf.cast(xyz_normalized_pixels > (epsilon**3), dtype=tf.float32)
                fxfyfz_pixels = (xyz_normalized_pixels / (3 * epsilon**2) + 4/29) * linear_mask + (xyz_normalized_pixels ** (1/3)) * exponential_mask

                # convert to lab
                fxfyfz_to_lab = tf.constant([
                    #  l       a       b
                    [  0.0,  500.0,    0.0], # fx
                    [116.0, -500.0,  200.0], # fy
                    [  0.0,    0.0, -200.0], # fz
                ])
                lab_pixels = tf.matmul(fxfyfz_pixels, fxfyfz_to_lab) + tf.constant([-16.0, 0.0, 0.0])

            return tf.reshape(lab_pixels, tf.shape(rgb_input))
        
    def lab_to_rgb(self, tf, lab):
        with tf.name_scope("lab_to_rgb"):
            lab_pixels = tf.reshape(lab, [-1, 3])

            # https://en.wikipedia.org/wiki/Lab_color_space#CIELAB-CIEXYZ_conversions
            with tf.name_scope("cielab_to_xyz"):
                # convert to fxfyfz
                lab_to_fxfyfz = tf.constant([
                    #   fx      fy        fz
                    [1/116.0, 1/116.0,  1/116.0], # l
                    [1/500.0,     0.0,      0.0], # a
                    [    0.0,     0.0, -1/200.0], # b
                ])
                fxfyfz_pixels = tf.matmul(lab_pixels + tf.constant([16.0, 0.0, 0.0]), lab_to_fxfyfz)

                # convert to xyz
                epsilon = 6/29
                linear_mask = tf.cast(fxfyfz_pixels <= epsilon, dtype=tf.float32)
                exponential_mask = tf.cast(fxfyfz_pixels > epsilon, dtype=tf.float32)
                xyz_pixels = (3 * epsilon**2 * (fxfyfz_pixels - 4/29)) * linear_mask + (fxfyfz_pixels ** 3) * exponential_mask

                # denormalize for D65 white point
                xyz_pixels = tf.multiply(xyz_pixels, [0.950456, 1.0, 1.088754])

            with tf.name_scope("xyz_to_srgb"):
                xyz_to_rgb = tf.constant([
                    #     r           g          b
                    [ 3.2404542, -0.9692660,  0.0556434], # x
                    [-1.5371385,  1.8760108, -0.2040259], # y
                    [-0.4985314,  0.0415560,  1.0572252], # z
                ])
                rgb_pixels = tf.matmul(xyz_pixels, xyz_to_rgb)
                # avoid a slightly negative number messing up the conversion
                rgb_pixels = tf.clip_by_value(rgb_pixels, 0.0, 1.0)
                linear_mask = tf.cast(rgb_pixels <= 0.0031308, dtype=tf.float32)
                exponential_mask = tf.cast(rgb_pixels > 0.0031308, dtype=tf.float32)
                srgb_pixels = (rgb_pixels * 12.92 * linear_mask) + ((rgb_pixels ** (1/2.4) * 1.055) - 0.055) * exponential_mask

            return tf.reshape(srgb_pixels, tf.shape(lab))