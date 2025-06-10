import math

import numpy
import pytest

from autotrainer.core import Offset3DTuple


def _offset_equal(o1, o2):
    assert isinstance(o1, Offset3DTuple)
    assert isinstance(o2, Offset3DTuple)
    for v1, v2 in zip(o1, o2):
        if ((math.isnan(v1) and math.isnan(v2)
        or (math.isinf(v1) and math.isinf(v2)))):
            continue
        if v1 != v2:
            return False
    return True


@pytest.mark.parametrize("values", [
    (1, 2, 3),
    (0, 0, 0),
    (-1, -1, math.nan),
])
@pytest.mark.parametrize("args_cls", [list, tuple, numpy.asarray])
def test_offset_3d_constructor_variants(values, args_cls):
    o_1 = Offset3DTuple(*args_cls(values))
    o_2 = Offset3DTuple(args_cls(values))
    assert len(o_1) == 3
    assert _offset_equal(o_1, o_2)
    o_1 = Offset3DTuple(o_1.x + 10, o_1.y, o_1.z)
    assert o_1 != o_2


def test_with_generator():
    # same than with list/tuple unpacking
    assert Offset3DTuple(*(i for i in range(3))) == (0, 1, 2)
    # but :
    with pytest.raises(TypeError):
        Offset3DTuple(i for i in range(3))


def test_accessors():
    o = Offset3DTuple(1, 2, 3)
    assert o.x == 1
    assert o.y == 2
    assert o.z == 3


@pytest.mark.parametrize("base_cls1,base_cls2", [
    (Offset3DTuple, list),
    (Offset3DTuple, numpy.asarray),
    (numpy.asarray, Offset3DTuple),
    (tuple, Offset3DTuple),
])
def test_addition(base_cls1, base_cls2):
    if base_cls1 != Offset3DTuple and base_cls2 != Offset3DTuple:
        pytest.skip("need one")
    o1 = base_cls1((1, 2, 3))
    o2 = base_cls2((-1, 3, 6))
    res = o1 + o2
    res_as_offset = Offset3DTuple(res)
    assert res_as_offset == (0, 5, 9)


@pytest.mark.parametrize("base_cls1,base_cls2", [
    (Offset3DTuple, list),
    (Offset3DTuple, numpy.asarray),
    (numpy.asarray, Offset3DTuple),
    (tuple, Offset3DTuple),
])
def test_substraction(base_cls1, base_cls2):
    o1 = base_cls1((1, 2, 3))
    o2 = base_cls2((-1, 3, 6))
    res = o1 - o2
    # if result is numpy ndarray, we want convert, otherwise == after needs .all()
    res_as_offset = Offset3DTuple(res)
    assert res_as_offset == (2, -1, -3)


def test_negative():
    offset = Offset3DTuple(1, 2, 3)
    neg_offset = - offset
    assert neg_offset == (-1, -2, -3)


def test_unpack():
    o = Offset3DTuple(1, 2, 3)
    assert len(o) == 3
    x, y, z = o
    assert x == 1
    assert y == 2
    assert z == 3


@pytest.mark.parametrize("args", [
    (),
    (1,),
    (1, 2),
    (1, 2, 3, 4),
])
@pytest.mark.parametrize("args_cls", [list, tuple, numpy.asarray])
def test_fail_with_invalid_args(args, args_cls):
    with pytest.raises(TypeError):
        Offset3DTuple(*args_cls(args))


def test_repr_and_str():
    o = Offset3DTuple((1, 2, 3))
    assert str(o) == "(1, 2, 3)"
    assert repr(o) == "(1, 2, 3)"
