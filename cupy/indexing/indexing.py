import numpy
import six

import cupy
from cupy import elementwise
from cupy import internal


def take(a, indices, axis=None, out=None):
    """Takes elements of an array at specified indices along an axis.

    This is an implementation of "fancy indexing" at single axis.

    This function does not support ``mode`` option.

    Args:
        a (cupy.ndarray): Array to extract elements.
        indices (int or array-like): Indices of elements that this function
            takes.
        axis (int): The axis along which to select indices. The flattened input
            is used by default.
        out (cupy.ndarray): Output array. If provided, it should be of
            appropriate shape and dtype.

    Returns:
        cupy.ndarray: The result of fancy indexing.

    .. seealso:: :func:`numpy.take`

    """
    if axis is None:
        a = a.ravel()
        lshape = ()
        rshape = ()
    else:
        if axis >= a.ndim:
            raise ValueError('Axis overrun')
        lshape = a.shape[:axis]
        rshape = a.shape[axis + 1:]

    if numpy.isscalar(indices):
        a = cupy.rollaxis(a, axis)
        if out is None:
            return a[indices].copy()
        else:
            out[:] = a[indices]
            return out
    elif not isinstance(indices, cupy.ndarray):
        indices = cupy.array(indices, dtype=int)

    out_shape = lshape + indices.shape + rshape
    if out is None:
        out = cupy.empty(out_shape, dtype=a.dtype)
    else:
        if out.dtype != a.dtype:
            raise TypeError('Output dtype mismatch')
        if out.shape != out_shape:
            raise ValueError('Output shape mismatch')

    cdim = indices.size
    rdim = internal.prod(rshape)
    indices = cupy.reshape(
        indices, (1,) * len(lshape) + indices.shape + (1,) * len(rshape))
    return _take_kernel(a, indices, cdim, rdim, out)


def choose(a, choices, out=None, mode='raise'):
    n = choices.shape[0]

    # broadcast `a` and `choices[i]` for all i
    if a.ndim < choices.ndim - 1:
        for i in range(choices.ndim - 1 - a.ndim):
            a = cupy.expand_dims(a, 0)
    elif a.ndim > choices.ndim - 1:
        for i in range(a.ndim + 1 - choices.ndim):
            choices = cupy.expand_dims(choices, 1)
    ba, bcs = cupy.broadcast_arrays(a, choices)

    n_channel = numpy.prod(bcs[0].shape)
    if mode == 'raise':
        if not ((a < n).all() and (0 <= a).all()):
            raise ValueError('invalid entry in choice array')
        c = _choose_kernel(ba[0], bcs, n_channel)
    elif mode == 'wrap':
        ba = ba[0] % n
        c = _choose_kernel(ba, bcs, n_channel)
    elif mode == 'clip':
        c = _choose_clip_kernel(ba[0], bcs, n_channel, n)
    else:
        raise TypeError('clipmode not understood')

    return c


# TODO(okuta): Implement compress


def diagonal(a, offset=0, axis1=0, axis2=1):
    """Returns specified diagonals.

    This function extracts the diagonals along two specified axes. The other
    axes are not changed. This function returns a writable view of this array
    as NumPy 1.10 will do.

    Args:
        a (cupy.ndarray): Array from which the diagonals are taken.
        offset (int): Index of the diagonals. Zero indicates the main
            diagonals, a positive value upper diagonals, and a negative value
            lower diagonals.
        axis1 (int): The first axis to take diagonals from.
        axis2 (int): The second axis to take diagonals from.

    Returns:
        cupy.ndarray: A view of the diagonals of ``a``.

    .. seealso:: :func:`numpy.diagonal`

    """
    if axis1 < axis2:
        min_axis, max_axis = axis1, axis2
    else:
        min_axis, max_axis = axis2, axis1

    tr = list(six.moves.range(a.ndim))
    del tr[max_axis]
    del tr[min_axis]
    if offset >= 0:
        a = cupy.transpose(a, tr + [axis1, axis2])
    else:
        a = cupy.transpose(a, tr + [axis2, axis1])
        offset = -offset

    diag_size = max(0, min(a.shape[-2], a.shape[-1] - offset))
    ret_shape = a.shape[:-2] + (diag_size,)
    if diag_size == 0:
        return cupy.empty(ret_shape, dtype=a.dtype)

    a = a[..., :diag_size, offset:offset + diag_size]

    ret = a.view()
    ret._shape = a.shape[:-2] + (diag_size,)
    ret._strides = a.strides[:-2] + (a.strides[-1] + a.strides[-2],)
    ret._size = internal.prod(ret._shape)
    ret._c_contiguous = -1
    ret._f_contiguous = -1
    return ret


# TODO(okuta): Implement select


_take_kernel = elementwise.ElementwiseKernel(
    'raw T a, S indices, int64 cdim, int64 rdim',
    'T out',
    '''
      long long li = i / (rdim * cdim);
      long long ri = i % rdim;
      out = a[(li * cdim + indices) * rdim + ri];
    ''',
    'cupy_take')

_choose_kernel = elementwise.ElementwiseKernel(
    'S a, raw T choices, int32 n_channel',
    'T y',
    'y = choices[i + n_channel * a]',
    'cupy_choose')

_choose_clip_kernel = elementwise.ElementwiseKernel(
    'S a, raw T choices, int32 n_channel, int32 n',
    'T y',
    '''
      S x = a;
      if (a < 0) {
        x = 0;
      } else if (a >= n) {
        x = n - 1;
      }
      y = choices[i + n_channel * x];
    ''',
    'cupy_choose_clip')
