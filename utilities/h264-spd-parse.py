#!/usr/bin/env python
import re, sys
from base64 import standard_b64decode as b64decode
import math
import traceback

class BitStream(object):
	def __init__(self, bits, n_bits):
		self.bits = bits
		self.n_bits = n_bits
		self.pos = 0

	@staticmethod
	def get_bits(bits, off, n_bits):
		off_bytes = off / 8
		off_bits = off % 8
		end_off_bits = off + n_bits
		end_off_bytes = (end_off_bits + 7) / 8

		bits_read_once = (end_off_bytes - off_bytes) * 8
		value = 0
		for i in xrange(off_bytes, end_off_bytes):
			value <<= 8
			value |= ord(bits[i])

		# Remove off_bits, from MSB(most significant bit) to LSB
		value &= (1 << (bits_read_once - off_bits)) - 1
		value <<= off_bits
		value >>= bits_read_once - n_bits

		return value, end_off_bits

	@staticmethod
	def get_ue(bits, off):
		off_bytes = off / 8
		off_bits = off % 8

		leadingzeros = -off_bits

		tmp = ord(bits[off_bytes])
		tmp &= (1 << (8 - off_bits)) - 1

		while not tmp: 
			off_bytes += 1
			leadingzeros += 8
			tmp = ord(bits[off_bytes])
		else:
			for i in xrange(8-1, -1, -1):
				if tmp & (1 << i):
					break
				leadingzeros += 1

		off = off + leadingzeros + 1

		codenum = (1 << leadingzeros) - 1

		if leadingzeros > 0:
			r, off = BitStream.get_bits(bits, off, leadingzeros)

			codenum += r
		else:
			assert codenum == 0

		return codenum, off

	@staticmethod
	def get_se(bits, off):
		"""Stolen from python-bitstring _readse"""
		codenum, off = BitStream.get_ue(bits, off)

		m = (codenum + 1) / 2
		if codenum % 2:
			return m, off
		else:
			return -m, off

	def peek(self, fmt):
		off = self.pos
		bits = self.bits

		if fmt == 'ue':
			r, off = BitStream.get_ue(bits, off)
		elif fmt == 'se':
			r, off = BitStream.get_se(bits, off)
		else:
			m = re.match('(?P<type>[fbu])(?P<n_bits>[0-9][1-9]?)', fmt)
			assert m, "Unknown fmt '%s'" % fmt

			type_, n_bits_ = m.group('type'), int(m.group('n_bits'))

			if type_ in 'fbu':
				r, off = BitStream.get_bits(bits, off, n_bits_)

		if off > self.n_bits:
			raise IndexError, "bitstream out of range" 

		return r, off - self.pos

	def read2(self, fmt):
		r, n_bits = self.peek(fmt)
		self.pos += n_bits

		return r, n_bits

	def read(self, fmt):
		r, n_bits = self.read2(fmt)

		return r

	def n_unread_bits(self):
		return self.n_bits - self.pos

class Sheet(object):
	def __init__(self, my_val = None):
		self.__dict__['order'] = ['_']
		self.__dict__['__storage__'] = {'_': my_val}
		self.__dict__['__fmt__'] = lambda self,K,V: None

	def __iter__(self):
		for key in self.__dict__['order'][1:]:
			yield key

	def __len__(self):
		return len(self.__dict__['order'][1:])

	def __setattr__(self, key, value):
		if key.startswith('__') and key.endswith('__'):
			self.__dict__[key] = value
			return

		if not self.__storage__.has_key(key):
			self.__dict__['order'].append(key)

		self.__storage__[key] = value

		node = self
		while node.__dict__.has_key('parent'):
			parent, key = node.__dict__['parent']
			if not parent.__storage__.has_key(key):
				parent.__dict__['order'].append(key)

			parent.__storage__[key] = node
			del node.__dict__['parent']

			node = parent

	def __getattr__(self, key):
		if key == '_':
			return self.__storage__[key]

		try:
			ret = value = self.__storage__[key]
			if not isinstance(value, Sheet):
				ret = Sheet(value)
				ret.__dict__['parent'] = (self, key)
		except KeyError:
			ret = empty = Sheet()
			empty.__dict__['parent'] = (self, key)

		return ret

	def __delattr__(self, key):
		try:
			del self.__storage__[key]
			self.__dict__['order'].remove(key)
		except KeyError, k:
			raise AttributeError, k

	def fmt(self, key, value):
		external_format_func = self.__fmt__
		keyval_str = external_format_func(self, key, value)
		if keyval_str != None:
			return keyval_str

		if isinstance(value, Sheet):
			if value._ != None:
				lines = ['%s\t= %s:' % (key, repr(value._))]
			else:
				lines = ['%s:\n']

			indent = '  '
			lines += [(l.strip() and indent + l) or l.strip() \
				  for l in repr(value).split('\n')]

			keyval_str = '\n'.join(lines)
		elif isinstance(value, int):
			keyval_str = '%s\t= 0x%x(%d)' % (key, value, value)
		else:
			keyval_str = '%s\t= %s' % (key, repr(value))

		return keyval_str

	def __repr__(self):
		outputs = []

		for key in self.__dict__['order'][1:]:
			value = self.__storage__[key]

			keyval_str = self.fmt(key, value)

			outputs.append(keyval_str)

		return '\n'.join(outputs)

def format_colour_description(colour_description, key, value):
	ColorPrimaries = {
	1: "BT709", # also ITU-R BT1361 / IEC 61966-2-4 / SMPTE RP177 Annex B
	2: "UNSPECIFIED",
	4: "BT470M",
	5: "BT470BG", # also ITU-R BT601-6 625 / ITU-R BT1358 625 / ITU-R BT1700 625 PAL & SECAM
	6: "SMPTE170M", # also ITU-R BT601-6 525 / ITU-R BT1358 525 / ITU-R BT1700 NTSC
	7: "SMPTE240M", # functionally identical to above
	8: "FILM",
	}

	ColorTransferCharacteristic = {
	1: "BT709", # also ITU-R BT1361
	2: "UNSPECIFIED",
	4: "GAMMA22", # also also ITU-R BT470M / ITU-R BT1700 625 PAL & SECAM
	5: "GAMMA28", # also ITU-R BT470BG
	7: "SMPTE240M",
	}

	ColorSpace = {
	0: "RGB",
	1: "BT709", # also ITU-R BT1361 / IEC 61966-2-4 xvYCC709 / SMPTE RP177 Annex B
	2: "UNSPECIFIED",
	4: "FCC",
	5: "BT470BG", #  also ITU-R BT601-6 625 / ITU-R BT1358 625 / ITU-R BT1700 625 PAL & SECAM / IEC 61966-2-4 xvYCC601
	6: "SMPTE170M", # also ITU-R BT601-6 525 / ITU-R BT1358 525 / ITU-R BT1700 NTSC / functionally identical to above
	7: "SMPTE240M", 
	8: "YCOCG", # Used by Dirac / VC-2 and H.264 FRext, see ITU-T SG16
	}

	if key in ('color_primaries', 'transfer_characteristics', 'matrix_coefficients'):
		m = { 'color_primaries': ColorPrimaries,
		  'transfer_characteristics': ColorTransferCharacteristic,
		  'matrix_coefficients': ColorSpace }[key]
		return '%s\t=\t%s' % (key, m.get(value, '0x%x' % value))

def format_scaling_matrix(sheet, key, value):
	if key in ('scaling_matrix4x4', 'scaling_matrix8x8'):
		if key == 'scaling_matrix4x4':
			nr_col = nr_line = 4
		else:
			nr_col = nr_line = 8

		r = ['%s:' % key]
		for i in xrange(len(value)):
			matrix = value[i]

			for j in xrange(nr_line):
				if j == 0:
					indent = '%d: ' % i
				else:
					indent = '   '

				line = '%s%s' % (indent,
				  ','.join('%4d' % matrix[k] \
				    for k in xrange(j*nr_col, j*nr_col+nr_col)))
				r.append(line)

		return '\n'.join(r)

class SPS(Sheet):
	def fmt(self, key, value):
		r = format_scaling_matrix(self, key, value)
		if r != None:
			return r

		return super(SPS, self).fmt(key, value)

	def __repr__(self):
		width = self.pic_width_in_mbs._ * 16
		height = ((2 - self.frame_mbs_only_flag._) * \
			  (self.pic_height_in_map_units._) * 16)

		if self.frame_cropping_flag._:
			width -= self.frame_cropping_flag.frame_crop_bottom_offset * 2
			width -= self.frame_cropping_flag.frame_crop_top_offset * 2

			height -= self.frame_cropping_flag.frame_crop_right_offset * 2
			height -= self.frame_cropping_flag.frame_crop_left_offset * 2

		max_fps = 0
		if self.vui_parameters_present_flag.timing_info_present_flag._:
			tinfo = self.vui_parameters_present_flag. \
				timing_info_present_flag
			max_fps = int(math.ceil(
			  tinfo.time_scale._ / (2.0 * tinfo.num_units_in_tick._) ))

		flags = ((self.frame_mbs_only_flag._ and 'FRM') or \
			 (self.frame_mbs_only_flag.mb_adaptive_frame_field_flag._ and \
			 'MB-AFF' or 'PIC-AFF'),
			 self.frame_mbs_only_flag._ and '8B8' or None,
			 self.vui_parameters_present_flag._ and 'VUI' or None)

		return 'SPS summ: %dx%d@%d [%s]\n%s' %(width, height, max_fps,
			' '.join(filter(None, flags)),
			super(SPS, self).__repr__())

class PPS(Sheet):
	def fmt(self, key, value):
		r = format_scaling_matrix(self, key, value)
		if r != None:
			return r

		return super(PPS, self).fmt(key, value)

	def __repr__(self):
		flags = (self.entropy_coding_mode_flag._ and 'CABAC' or 'CAVLC',
			 self.weighted_pred_flag._ and 'weighted' or None,
			 self.deblocking_filter_control_present_flag._ and 'LPAR' or None,
			 self.constrained_intra_pred_flag._ and 'CONSTR' or None,
			 self.redundant_pic_cnt_present_flag._ and 'REDU' or None,
			 self.transform_8x8_mode_flag._ and '8x8DCT' or None)
			
		return 'PPS summ: [%s]\n%s' %(
			' '.join(filter(None, flags)),
			super(PPS, self).__repr__())


class SPD(object):
	NAL_TYPE_SPS = 7
	NAL_TYPE_PPS = 8
	DefaultScalingMatrix4x4 = (
	( 6, 13, 20, 28,
	 13, 20, 28, 32,
	 20, 28, 32, 37,
	 28, 32, 37, 42),
	(10, 14, 20, 24,
	 14, 20, 24, 27,
	 20, 24, 27, 30,
	 24, 27, 30, 34))
	DefaultScalingMatrix8x8 = (
	( 6, 10, 13, 16, 18, 23, 25, 27, 
	 10, 11, 16, 18, 23, 25, 27, 29, 
	 13, 16, 18, 23, 25, 27, 29, 31, 
	 16, 18, 23, 25, 27, 29, 31, 33, 
	 18, 23, 25, 27, 29, 31, 33, 36, 
	 23, 25, 27, 29, 31, 33, 36, 38, 
	 25, 27, 29, 31, 33, 36, 38, 40, 
	 27, 29, 31, 33, 36, 38, 40, 42), 
	( 9, 13, 15, 17, 19, 21, 22, 24, 
	 13, 13, 17, 19, 21, 22, 24, 25, 
	 15, 17, 19, 21, 22, 24, 25, 27, 
	 17, 19, 21, 22, 24, 25, 27, 28, 
	 19, 21, 22, 24, 25, 27, 28, 30, 
	 21, 22, 24, 25, 27, 28, 30, 32, 
	 22, 24, 25, 27, 28, 30, 32, 33, 
	 24, 25, 27, 28, 30, 32, 33, 35))

	PixelAspect = ((0, 1),
	 (1,  1),  (12, 11), (10, 11), (16, 11),
	 (40, 33), (24, 11), (20, 11), (32, 11),
	 (80, 33), (18, 11), (15, 11), (64, 33),
	 (160,99), (4,  3),  (3,  2),  (2, 1))

	def __init__(self, sprop_parameter_sets):
		self.spss = {}
		self.ppss = {}

		for nal in sprop_parameter_sets.split(','):
			nal = b64decode(nal)

			nal_type, ref_idc, rbsp = self.__decode_nal(nal)

			# Raw Byte Sequence PayLoad
			self.rbsp = rbsp
			if nal_type == self.NAL_TYPE_SPS:
				sps = SPS()
				sps.ref_idc = ref_idc

				try:
					del self.__curr_sps
				except AttributeError:
					pass

				try:
					self.__sps(sps)
				except (AssertionError, IndexError) as e:
					print >>sys.stdout, sps
					print >>sys.stderr, \
					  '\n*** Error ***\n%s', traceback.format_exc()
				else:
					self.spss[sps.sps_id._] = sps
					self.__curr_sps = sps
			elif nal_type == self.NAL_TYPE_PPS: 
				pps = PPS()
				pps.ref_idc = ref_idc

				try:
					self.__pps(pps)
				except (AssertionError, IndexError, AttributeError, KeyError) as e:
					print >>sys.stdout, pps
					print >>sys.stderr, \
					  '\n*** Error ***\n%s', traceback.format_exc()
				else:
					self.ppss[pps.pps_id._] = pps
			else:
				print >>sys.stderr, 'Ignore Unknown NAL type %s' % nal_type
		del self.rbsp

	def __repr__(self):
		try:
			sps_pps = []
			unpaired_sps = self.spss.keys()
			for pps_id in self.ppss:
				pps = self.ppss[pps_id]
				my_sps = self.spss[pps.sps_id._]
				unpaired_sps.remove(pps.sps_id._)

				sps_pps.append('*** %s\n\n*** %s' % (
				  repr(my_sps), repr(pps)))

			for sps_id in unpaired_sps:
				_sps = self.spss[sps_id]
				sps_pps.append(repr(_sps))

			return ('-' * 15).join(sps_pps)
		except AttributeError:
			return ''

	@staticmethod
	def __decode_nal(bits):
		head = ord(bits[0])

		nal_type = head & 0x1f
		forbidden_zero_bit = head >> 7
		ref_idc = (head >> 5) & 0x3

		assert forbidden_zero_bit == 0,\
		  'forbidden_zero_bit is not zero, invalid NAL!'

		bits = bits[1:]
		bits_len = len(bits)
		for i in xrange(0, bits_len-1, 2):
			if ord(bits[i]):
				continue

			if i > 0 and ord(bits[i-1]) == 0:
				i -= 1

			if i + 2 < bits_len and \
			  ord(bits[i+1]) == 0 and \
			  ord(bits[i+2]) <= 3:
				if ord(bits[i+2]) != 3:
					# startcode, so we must be past the end
					bits_len = i

				break
		else:
			i += 2

		if i < bits_len - 1: # has escaped 0
			# use second escape buffer for inter data
			bits_new = list(bits) + ['\0',] * 8 # plus FF_INPUT_BUFFER_PADDING_SIZE
			si = di = i
			while si + 2 < bits_len:
				# remove escapes (very rare 1:2^22)
				if ord(bits[si + 2]) > 3:
					bits_new[di] = bits[si]
					bits_new[di+1] = bits[si+1]
					di += 2
					si += 2
				elif ord(bits[si]) == 0 and ord(bits[si+1]) == 0:
					if ord(bits[si+2]) == 3: # escape
						bits_new[di] = bits_new[di+1] = '\0'
						di += 2
						si += 3
						continue
					else: # next start code
						break
				bits_new[di] = bits[si]
				di += 1
				si += 1
			else:
				while si < bits_len:
					bits_new[di] = bits[si]
					di += 1
					si += 1

			bits = ''.join(bits_new)
			bits_len = di

		if bits_len:
			v = ord(bits[bits_len-1])

			for trailing in xrange(1, 9):
				if v & 1:
					break
				v >>= 1
			else:
				trailing = 0

			bits_len = 8 * bits_len - trailing

		rbsp = BitStream(bits, bits_len)
		return nal_type, ref_idc, rbsp

	def __decode_scaling_list(self, sz_scaling_list, jvt_list, fallback_list):
		last_scale = 8
		next_scale = 8
		scaling_list = [0] * sz_scaling_list

		seq_scaling_list_present_flag = self.rbsp.read('u1')
		if not seq_scaling_list_present_flag:
			return fallback_list

		for i in xrange(sz_scaling_list):
			if next_scale != 0:
				delta_scale = self.rbsp.read('se')
				next_scale = (last_scale + delta_scale) % 256
				if i == 0 and next_scale == 0:
					return jvt_list

			if next_scale == 0:
				scaling_list[i] = last_scale
			else:
				scaling_list[i] = next_scale

			last_scale = scaling_list[i]

		return tuple(scaling_list)

	def __decode_scaling_matrices(self, sps, pps, is_sps):
		if (not is_sps) and sps.seq_scaling_matrix_present_flag._:
			sps_scaling_matrix4x4 = \
			  sps.seq_scaling_matrix_present_flag.scaling_matrix4x4._
			sps_scaling_matrix8x8 = \
			  sps.seq_scaling_matrix_present_flag.scaling_matrix8x8._

			fallback_list = (
			  sps_scaling_matrix4x4[0],
			  sps_scaling_matrix4x4[3],
			  sps_scaling_matrix8x8[0],
			  sps_scaling_matrix8x8[3])
		else:
			fallback_list = (
			  self.DefaultScalingMatrix4x4[0],
			  self.DefaultScalingMatrix4x4[1],
			  self.DefaultScalingMatrix8x8[0],
			  self.DefaultScalingMatrix8x8[1])

		scaling_matrix4x4 = []
		# Intra, Y
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[0],
						 fallback_list[0]))

		# Intra, Cr
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[0],
						 scaling_matrix4x4[0]))

		# Intra, Cb
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[0],
						 scaling_matrix4x4[1]))

		# Inter, Y
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[1],
						 fallback_list[1]))

		# Inter, Cr
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[1],
						 scaling_matrix4x4[3]))

		# Inter, Cb
		scaling_matrix4x4.append(
		  self.__decode_scaling_list(16, self.DefaultScalingMatrix4x4[1],
						 scaling_matrix4x4[4]))

		scaling_matrix8x8 = None
		if is_sps or pps.transform_8x8_mode_flag._:
			scaling_matrix8x8 = ([16,] * 64,) * 6

			# Intra, Y
			scaling_matrix8x8[0] = \
		  	  self.__decode_scaling_list(64, self.DefaultScalingMatrix8x8[0],
							 fallback_list[2])

			if profile_idc.chroma_format_idc._ == 3:
				# Intra, Cr
				scaling_matrix8x8[1] = \
				  self.__decode_scaling_list(64,
							     self.DefaultScalingMatrix8x8[0],
							     scaling_matrix8x8[0])

				# Intra, Cb
				scaling_matrix8x8[2] = \
				  self.__decode_scaling_list(64,
							     self.DefaultScalingMatrix8x8[0],
							     scaling_matrix8x8[1])
			# Inter, Y
			scaling_matrix8x8[3] = \
		  	  self.__decode_scaling_list(64, self.DefaultScalingMatrix8x8[1],
							 fallback_list[3])

			if profile_idc.chroma_format_idc._ == 3:
				# Intra, Cr
				scaling_matrix8x8[4] = \
				  self.__decode_scaling_list(64,
							     self.DefaultScalingMatrix8x8[1],
							     scaling_matrix8x8[3])

				# Intra, Cb
				scaling_matrix8x8[5] = \
				  self.__decode_scaling_list(64,
							     self.DefaultScalingMatrix8x8[1],
							     scaling_matrix8x8[4])
		return scaling_matrix4x4, scaling_matrix8x8

	def __decode_hrd_parameters(self, hrd):
		def fmt_hrd(hrd, k, v):
			if k != 'cpb':
				return

			lines = []
			cpb_count = len(v)
			for i in xrange(cpb_count):
				lines.append('cpb[%d/%d]:' % (i+1, cpb_count))
				lines.append(
				  '  bit_rate_value\t= %(bit_rate_value)d\n' \
				  '  cpb_size_value\t= %(cpb_size_value)d\n' \
				  '  cbr_flag\t= %(cbr_flag)d' % v[i])
			return '\n'.join(lines)

		hrd.__fmt__ = fmt_hrd

		cpb_count = self.rbsp.read('ue') + 1
		assert cpb_count <= 32, 'cpb_count %d invalid\n' % cpb_count

		hrd.bit_rate_scale = self.rbsp.read('u4')
		hrd.cpb_size_scale = self.rbsp.read('u4')

		cpb = []
		for i in xrange(cpb_count):
			bit_rate_value = self.rbsp.read('ue') + 1
			cpb_size_value = self.rbsp.read('ue') + 1
			cbr_flag = self.rbsp.read('u1')

			cpb.append({ 'bit_rate_value': bit_rate_value,
			  'cpb_size_value': cpb_size_value,
			  'cbr_flag': cbr_flag })
		hrd.cpb = cpb

		hrd.initial_cpb_removal_delay_length = self.rbsp.read('u5') + 1
		hrd.cpb_removal_delay_length = self.rbsp.read('u5') + 1
		hrd.dpb_removal_delay_length = self.rbsp.read('u5') + 1
		hrd.time_offset_length = self.rbsp.read('u5')

	def __decode_vui_parameters(self, vui_parameters):
		vui_parameters. \
		  aspect_ratio_info_present_flag = self.rbsp.read('u1')

		fmt_sar = lambda self, k, v: \
		  k == 'sar' and '%s\t= %s/%s' % (k, v[0], v[1]) or None
		if vui_parameters.aspect_ratio_info_present_flag._:
			aspect_ratio_idc = Sheet()
			aspect_ratio_idc._ = self.rbsp.read('u8')
			if aspect_ratio_idc._ == 255:
				sar_num = self.rbsp.read('u16')
				sar_den = self.rbsp.read('u16')
			else:
				try:
					sar_num, sar_den = \
					  self.PixelAspect[aspect_ratio_idc._]
				except IndexError:
					assert 0, "illegal aspect_ratio_idc '%d'" \
						  % aspect_ratio_idc._

			aspect_ratio_idc.sar = (sar_num, sar_den)

			aspect_ratio_idc.__fmt__ = fmt_sar
			vui_parameters.aspect_ratio_info_present_flag. \
			  aspect_ratio_idc = aspect_ratio_idc
		else:
			vui_parameters.aspect_ratio_info_present_flag. \
			  sar = (0, 1)
			vui_parameters.aspect_ratio_info_present_flag. \
			  __fmt__ = fmt_sar

		vui_parameters.overscan_info_present_flag = self.rbsp.read('u1')
		if vui_parameters.overscan_info_present_flag._:
			vui_parameters.overscan_info_present_flag. \
			  overscan_appropriate_flag = self.rbsp.read('u1')

		vui_parameters.video_signal_type_present_flag = \
		  self.rbsp.read('u1')
		if vui_parameters.video_signal_type_present_flag._:
			vui_parameters.video_signal_type_present_flag. \
			  video_format = self.rbsp.read('u3')

			vui_parameters.video_signal_type_present_flag. \
			  video_full_range_flag = self.rbsp.read('u1')

			vui_parameters.video_signal_type_present_flag. \
			  colour_description_present_flag = self.rbsp.read('u1')

			if vui_parameters.video_signal_type_present_flag. \
			   colour_description_present_flag._:
				tmp = Sheet(1)
				tmp.__fmt__ = format_colour_description

				tmp.color_primaries = self.rbsp.read('u8')
				tmp.transfer_characteristics = self.rbsp.read('u8')
				tmp.matrix_coefficients = self.rbsp.read('u8')
				vui_parameters.video_signal_type_present_flag. \
				  colour_description_present_flag = tmp

		vui_parameters.chroma_loc_info_present_flag = self.rbsp.read('u1')
		if vui_parameters.chroma_loc_info_present_flag._:
			vui_parameters.chroma_loc_info_present_flag. \
			  chroma_sample_loc_type_top_field = self.rbsp.read('ue')
			vui_parameters.chroma_loc_info_present_flag. \
			  chroma_sample_location_type_bottom_field = self.rbsp.read('ue')

		vui_parameters.timing_info_present_flag = self.rbsp.read('u1')
		if vui_parameters.timing_info_present_flag._:
			tmp = Sheet(1)

			tmp.num_units_in_tick = self.rbsp.read('u32')
			tmp.time_scale = self.rbsp.read('u32')

			tmp.fixed_frame_rate_flag = self.rbsp.read('u1')
			vui_parameters.timing_info_present_flag = tmp 

			assert tmp.num_units_in_tick._ != 0 and tmp.time_scale._ != 0,\
			  "time_scale/num_units_in_tick invalid or unsupported (%d/%d)" \
			  % (tmp.time_scale._, tmp.num_units_in_tick._) 

		vui_parameters.nal_hrd_parameters_present_flag = self.rbsp.read('u1')
		if vui_parameters.nal_hrd_parameters_present_flag._:
			self.__decode_hrd_parameters(
			  vui_parameters.nal_hrd_parameters_present_flag)

		vui_parameters.vcl_hrd_parameters_present_flag = self.rbsp.read('u1')
		if vui_parameters.vcl_hrd_parameters_present_flag._:
			self.__decode_hrd_parameters(
			  vui_parameters.vcl_hrd_parameters_present_flag) 

		if vui_parameters.nal_hrd_parameters_present_flag._ or \
		   vui_parameters.vcl_hrd_parameters_present_flag._:
			vui_parameters.low_delay_hrd_flag = self.rbsp.read('u1')

		vui_parameters.pic_struct_present_flag = self.rbsp.read('u1')
		vui_parameters.bitstream_restriction_flag = self.rbsp.read('u1')
		if vui_parameters.bitstream_restriction_flag._:
			tmp = Sheet(1)
			tmp.motion_vectors_over_pic_boundaries_flag = \
			  self.rbsp.read('u1')
			tmp.max_bytes_per_pic_denom = self.rbsp.read('ue')
			tmp.max_bits_per_mb_denom = self.rbsp.read('ue')
			tmp.log2_max_mv_length_horizontal = self.rbsp.read('ue')
			tmp.log2_max_mv_length_vertical = self.rbsp.read('ue')
			tmp.max_num_reorder_frames = self.rbsp.read('ue')
			tmp.max_dec_frame_buffering = self.rbsp.read('ue')

			vui_parameters.bitstream_restriction_flag = tmp

			assert tmp.max_num_reorder_frames._ <= 16, \
			  'illegal max_num_reorder_frames %d' % tmp.max_num_reorder_frames._

	def __sps(self, sps):
		profile_idc = self.rbsp.read('u8')
		constraint_set_flags = self.rbsp.read('f1')
		constraint_set_flags |= self.rbsp.read('f1') << 1
		constraint_set_flags |= self.rbsp.read('f1') << 2
		constraint_set_flags |= self.rbsp.read('f1') << 3
		self.rbsp.read('f4') # reserved
		level_idc = self.rbsp.read('u8')
		sps_id = self.rbsp.read('ue')

		sps.sps_id = sps_id
		sps.profile_idc = profile_idc
		sps.level_idc = level_idc
		sps.constraint_set_flags = constraint_set_flags

		sps.scaling_matrix4x4 = ((16,) * 16,) * 6
		sps.scaling_matrix8x8 = ((16,) * 64,) * 6

		if profile_idc in [100, 110, 122, 244, 44, 83, 86, 118, 128, 138]:
			sps.profile_idc.chroma_format_idc = self.rbsp.read('ue')
			assert sps.profile_idc.chroma_format_idc._ <= 3,\
			  "chroma_format_idc (%d) out o range" % \
			  sps.profile_idc.chroma_format_idc._

			if sps.profile_idc.chroma_format_idc._ == 3:
				sps.profile_idc.chroma_format_idc.separate_colour_plane_flag = \
				  self.rbsp.read('u1')

			sps.profile_idc.bit_depth_luma = self.rbsp.read('ue') + 8
			sps.profile_idc.bit_depth_chroma = self.rbsp.read('ue') + 8
			sps.profile_idc.qpprime_y_zero_transform_bypass_flag = \
			  self.rbsp.read('u1')
			sps.profile_idc.seq_scaling_matrix_present_flag = \
			  self.rbsp.read('u1')

			if sps.profile_idc.seq_scaling_matrix_present_flag._:
				scaling_matrix4x4, scaling_matrix8x8 = \
				  self.__decode_scaling_matrices(sps, None, True)
				del sps.scaling_matrix4x4
				del sps.scaling_matrix8x8
				sps.profile_idc.seq_scaling_matrix_present_flag. \
				  scaling_matrix4x4 = scaling_matrix4x4
				sps.profile_idc.seq_scaling_matrix_present_flag. \
				  scaling_matrix8x8 = scaling_matrix8x8

				sps.profile_idc.seq_scaling_matrix_present_flag. \
				  __fmt__ = format_scaling_matrix
		else:
			sps.profile_idc.chroma_format_idc = 1
			sps.profile_idc.bit_depth_luma = 8
			sps.profile_idc.bit_depth_chroma = 8

		sps.profile_idc.__fmt__ = \
		  lambda o, k, v: k == 'chroma_format_idc' and \
		    '%s\t= %s' % (k, ['Gray', '420', '422', '444'][v]) \
		    or None

		sps.log2_max_frame_num = self.rbsp.read('ue') + 4
		assert sps.log2_max_frame_num._ >= 4 and sps.log2_max_frame_num._ <= 16,\
		  "log2_max_frame_num_minus4 out of range (0-12): %d" % \
		  (sps.log2_max_frame_num._ - 4)

		sps.pic_order_cnt_type = self.rbsp.read('ue')
		if sps.pic_order_cnt_type._ == 0:
			sps.pic_order_cnt_type.log2_max_pic_order_cnt_lsb = \
			  self.rbsp.read('ue') + 4
		elif sps.pic_order_cnt_type._ == 1:
			sps.pic_order_cnt_type. \
			  delta_pic_order_always_zero_flag = self.rbsp.read('u1')
			sps.pic_order_cnt_type. \
			  offset_for_non_ref_pic = self.rbsp.read('se')
			sps.pic_order_cnt_type. \
			  offset_for_top_to_bottom_field = self.rbsp.read('se')

			sps.pic_order_cnt_type. \
			  num_ref_frames_in_pic_order_cnt_cycle = self.rbsp.read('ue')
			offset_for_ref_frame = []
			for i in xrange(num_ref_frames_in_pic_order_cnt_cycle):
				offset_for_ref_frame.append(self.rbsp.read('se'))
			sps.pic_order_cnt_type.num_ref_frames_in_pic_order_cnt_cycle. \
				offset_for_ref_frame = offset_for_ref_frame
		else:
			assert sps.pic_order_cnt_type._ == 2,\
			  "illegal pic_order_cnt_type type %d" % sps.pic_order_cnt_type._

		sps.max_num_ref_frames = self.rbsp.read('ue')
		sps.gaps_in_frame_num_value_allowed_flag = self.rbsp.read('u1')

		sps.pic_width_in_mbs = self.rbsp.read('ue') + 1
		sps.pic_height_in_map_units = self.rbsp.read('ue') + 1

		sps.frame_mbs_only_flag = self.rbsp.read('u1')

		if not sps.frame_mbs_only_flag._:
			sps.frame_mbs_only_flag. \
			  mb_adaptive_frame_field_flag = self.rbsp.read('u1')
		else:
			sps.frame_mbs_only_flag. \
			  mb_adaptive_frame_field_flag = 0

		sps.direct_8x8_inference_flag = self.rbsp.read('u1')
		assert sps.frame_mbs_only_flag._ or sps.direct_8x8_inference_flag._, \
		  'This stream was generated by a broken encoder, invalid 8x8 inference'

		sps.frame_cropping_flag = self.rbsp.read('u1')
		if sps.frame_cropping_flag._:
			sps.frame_cropping_flag. \
			  frame_crop_left_offset = self.rbsp.read('ue')
			sps.frame_cropping_flag. \
			  frame_crop_right_offset = self.rbsp.read('ue')
			sps.frame_cropping_flag. \
			  frame_crop_top_offset = self.rbsp.read('ue')
			sps.frame_cropping_flag. \
			  frame_crop_bottom_offset = self.rbsp.read('ue')

		sps.vui_parameters_present_flag = self.rbsp.read('u1')
		if sps.vui_parameters_present_flag._:
			self.__decode_vui_parameters(sps.vui_parameters_present_flag)

	def __pps(self, pps):
		pps.pps_id = self.rbsp.read('ue')
		pps.sps_id = self.rbsp.read('ue')
		pps.entropy_coding_mode_flag = self.rbsp.read('u1')
		pps.bottom_field_pic_order_in_frame_present_flag = \
		  self.rbsp.read('u1')
		pps.num_slice_groups = self.rbsp.read('ue') + 1

		qp_bd_offset = 6 * (
		  self.__curr_sps.profile_idc.bit_depth_luma._ - 8 )
		my_sps = self.spss[pps.sps_id._]

		if pps.num_slice_groups._ > 1:
			slice_group_map_type = self.rbsp.read('ue')
			tmp = Sheet(slice_group_map_type)

			if slice_group_map_type == 0:
				tmp.run_length = []
				for i in xrange(pps.num_slice_groups._):
					tmp.run_length._.append(
					  self.rbsp.read('ue') + 1)

			elif slice_group_map_type == 2:
				tmp.top_left = []
				tmp.bottom_right = []
				for i in xrange(pps.num_slice_groups._):
					tmp.top_left._.append(
					  self.rbsp.read('ue'))
					tmp.bottom_right._.append(
					  self.rbsp.read('ue'))

			elif slice_group_map_type in (3, 4, 5):
				tmp.slice_group_change_direction_flag = \
				  self.rbsp.read('u1')
				tmp.slice_group_change_rate = \
				  self.rbsp.read('ue') + 1
			elif slice_group_map_type == 6:
				tmp.pic_size_in_map_units = \
				  self.rbsp.read('ue') + 1
				
				slice_group_id = \
				  tmp.pic_size_in_map_units.slice_group_id = []
				bit_v = int(math.ceil(
					  math.log(pps.num_slice_groups._, 2) ))
				for i in xrange(tmp.pic_size_in_map_units._):
					slice_group_id.append(
					  self.rbsp.read('u%d' % bit_v))
			
			pps.num_slice_groups.slice_group_map_type = tmp or tmp._

		pps.num_ref_idx_l0_default_active = \
		  self.rbsp.read('ue') + 1
		pps.num_ref_idx_l1_default_active = \
		  self.rbsp.read('ue') + 1

		assert pps.num_ref_idx_l0_default_active._ < 33 and \
		       pps.num_ref_idx_l1_default_active._ < 33, \
		       "pps.num_ref_idx_l[01]_default_active: overflow"

		pps.weighted_pred_flag = self.rbsp.read('u1')
		pps.weighted_bipred_idc = self.rbsp.read('u2')
		pps.pic_init_qp = self.rbsp.read('se') + 26 + qp_bd_offset
		pps.pic_init_qs = self.rbsp.read('se') + 26 + qp_bd_offset

		pps.chroma_qp_index_offset = self.rbsp.read('se')
		pps.deblocking_filter_control_present_flag = self.rbsp.read('u1')
		pps.constrained_intra_pred_flag = self.rbsp.read('u1')
		pps.redundant_pic_cnt_present_flag = self.rbsp.read('u1')

		if my_sps.profile_idc.seq_scaling_matrix_present_flag._:
			pps.scaling_matrix4x4 = \
			  my_sps.profile_idc.seq_scaling_matrix_present_flag. \
			    scaling_matrix4x4._[:]

			pps.scaling_matrix8x8 = \
			  my_sps.profile_idc.seq_scaling_matrix_present_flag. \
			    scaling_matrix8x8._[:]
		else:
			pps.scaling_matrix4x4 = my_sps.scaling_matrix4x4._[:]
			pps.scaling_matrix8x8 = my_sps.scaling_matrix8x8._[:]

		if self.rbsp.n_unread_bits():
			pps.transform_8x8_mode_flag = self.rbsp.read('u1')
			pps.pic_scaling_matrix_present_flag = self.rbsp.read('u1')
			if pps.pic_scaling_matrix_present_flag._:
				scaling_matrix4x4, scaling_matrix8x8 = \
				  self.__decode_scaling_matrices(my_sps, pps, False)

				del pps.scaling_matrix4x4
				del pps.scaling_matrix8x8

				pps.pic_scaling_matrix_present_flag. \
				  scaling_matrix4x4 = pps.scaling_matrix4x4
				pps.pic_scaling_matrix_present_flag. \
				  scaling_matrix8x8 = pps.scaling_matrix8x8
				pps.pic_scaling_matrix_present_flag. \
				  __fmt__ = format_scaling_matrix

			pps.second_chroma_qp_index_offset = self.rbsp.read('se')


if __name__ == '__main__':
	try:
		sps = sys.argv[1]
#		sps = 'J0LgH41oBQBbpsgAAAMACAAAAwBAeKEVAA==,KM4ESSA='
#		sps = 'Z0IAKeNQFAe2AtwEBAaQeJEV,aM48gA=='
#		sps = 'Z0LAFKaBQfsBEAAAAwAQAAADA8jxQqoA,aM48gA=='
	except IndexError:
		sys.exit('Usage: %s <sprop-parameter-sets>' % sys.argv[0])

	print SPD(sps)

