#! /usr/bin/env python
#
# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Converts a cubic bezier curve to a quadratic spline with 
exactly two off curve points.

"""

from math import sqrt

import numpy
from numpy import array, dot
from fontTools.misc import bezierTools
from robofab.objects.objectsRF import RSegment, RPoint

def replaceSegments(contour, segments):
    try:
        return contour.replaceSegments(segments)
    except AttributeError:
        pass
    while len(contour):
        contour.removeSegment(0)
    for s in segments:
        contour.appendSegment(s.type, [(p.x, p.y) for p in s.points], s.smooth)


_zip = zip
def zip(*args):
    """Ensure each argument to zip has the same length."""
    if len(set(len(a) for a in args)) != 1:
        msg = "Args to zip in convertCurves.py should have equal lengths: "
        raise ValueError(msg + " ".join(str(a) for a in args))
    return _zip(*args)


def lerp(p1, p2, t):
    """Linearly interpolate between p1 and p2 at time t."""
    return p1 * (1 - t) + p2 * t


def extend(p1, p2, n):
    """Return the point extended from p1 in the direction of p2 scaled by n."""
    return p1 + (p2 - p1) * n


def dist(p1, p2):
    """Calculate the distance between two points."""
    return sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def bezierAt(p, t):
    """Return the point on a bezier curve at time t."""

    n = len(p)
    if n == 1:
        return p[0]
    return lerp(bezierAt(p[:n - 1], t), bezierAt(p[1:n], t), t)


def cubicApprox(p, t):
    """Approximate a cubic bezier curve with a quadratic one."""

    p1 = extend(p[0], p[1], 1.5)
    p2 = extend(p[3], p[2], 1.5)
    return [p[0], lerp(p1, p2, t), p[3]]


def calcIntersect(p):
    """Calculate the intersection of ab and cd, given [a, b, c, d]."""

    numpy.seterr(all="raise")
    a, b, c, d = p
    ab = b - a
    cd = d - c
    p = array([-ab[1], ab[0]])
    try:
        h = dot(a - c, p) / dot(cd, p)
    except FloatingPointError:
        raise ValueError("Parallel vectors given to calcIntersect.")
    return c + dot(cd, h)


def cubicApproxContour(p, n):
    """Approximate a cubic bezier curve with a contour of n quadratics.

    Returns None if n is 1 and the cubic's control vectors are parallel, since
    no quadratic exists with this cubic's tangents."""

    if n == 1:
        try:
            p1 = calcIntersect(p)
        except ValueError:
            return None
        return p[0], p1, p[3]

    contour = [p[0]]
    ts = [(float(i) / n) for i in range(1, n)]
    segments = [
        map(array, segment)
        for segment in bezierTools.splitCubicAtT(p[0], p[1], p[2], p[3], *ts)]
    for i in range(len(segments)):
        segment = cubicApprox(segments[i], float(i) / (n - 1))
        contour.append(segment[1])
    contour.append(p[3])
    return contour


def curveContourDist(bezier, contour):
    """Max distance between a bezier and quadratic contour at sampled ts."""

    TOTAL_STEPS = 20
    error = 0
    n = len(contour) - 2
    steps = TOTAL_STEPS / n
    for i in range(1, n + 1):
        segment = [
            contour[0] if i == 1 else segment[2],
            contour[i],
            contour[i + 1] if i == n else lerp(contour[i], contour[i + 1], 0.5)]
        for j in range(steps):
            p1 = bezierAt(bezier, (float(j) / steps + i - 1) / n)
            p2 = bezierAt(segment, float(j) / steps)
            error = max(error, dist(p1, p2))
    return error


def convertToQuadratic(p0,p1,p2,p3):
    MAX_N = 10
    MAX_ERROR = 10
    if not isinstance(p0, RPoint):
        return convertCollectionToQuadratic(p0, p1, p2, p3, MAX_N, MAX_ERROR)

    p = [array([i.x, i.y]) for i in [p0, p1, p2, p3]]
    for n in range(1, MAX_N + 1):
        contour = cubicApproxContour(p, n)
        if contour and curveContourDist(p, contour) <= MAX_ERROR:
            break
    return contour


def convertCollectionToQuadratic(p0, p1, p2, p3, maxN, maxErr):
    curves = [[array([i.x, i.y]) for i in p] for p in zip(p0, p1, p2, p3)]
    for n in range(1, maxN + 1):
        contours = [cubicApproxContour(c, n) for c in curves]
        if not all(contours):
            continue
        if max(curveContourDist(*a) for a in zip(curves, contours)) <= maxErr:
            break
    return contours


def cubicSegmentToQuadratic(c,sid):
    
    segment = c[sid]
    if (segment.type != "curve"):
        print "Segment type not curve"
        return
    
    #pSegment,junk = getPrevAnchor(c,sid)
    pSegment = c[sid-1] #assumes that a curve type will always be proceeded by another point on the same contour
    points = convertToQuadratic(pSegment.points[-1],segment.points[0],
                                segment.points[1],segment.points[2])

    try:
        return segment.asQuadratic([p[1:] for p in points])
    except AttributeError:
        pass
    return RSegment(
        'qcurve', [[int(i) for i in p] for p in points[1:]], segment.smooth)

def glyphCurvesToQuadratic(g):

    for c in g:
        segments = []
        for i in range(len(c)):
            s = c[i]
            if s.type == "curve":
                try:
                    segments.append(cubicSegmentToQuadratic(c, i))
                except Exception:
                    print g.name, i
                    raise
            else:
                segments.append(s)
        replaceSegments(c, segments)


class FontCollection:
    """A collection of fonts, or font components from different fonts.

    Behaves like a single instance of the component, allowing access into
    multiple fonts simultaneously for purposes of ensuring interpolation
    compatibility.
    """

    def __init__(self, fonts):
        self.init(fonts, GlyphCollection)

    def __getitem__(self, key):
        return self.children[key]

    def __len__(self):
        return len(self.children)

    def __str__(self):
        return str(self.instances)

    def init(self, instances, childCollectionType, getChildren=None):
        self.instances = instances
        childrenByInstance = map(getChildren, self.instances)
        self.children = map(childCollectionType, zip(*childrenByInstance))


class GlyphCollection(FontCollection):
    def __init__(self, glyphs):
        self.init(glyphs, ContourCollection)
        self.name = glyphs[0].name


class ContourCollection(FontCollection):
    def __init__(self, contours):
        self.init(contours, SegmentCollection)

    def replaceSegments(self, segmentCollections):
        segmentsByContour = zip(*[s.instances for s in segmentCollections])
        for contour, segments in zip(self.instances, segmentsByContour):
            replaceSegments(contour, segments)


class SegmentCollection(FontCollection):
    def __init__(self, segments):
        self.init(segments, None, lambda s: s.points)
        self.points = self.children
        self.type = segments[0].type

    def asQuadratic(self, newPoints=None):
        points = newPoints or self.children
        return SegmentCollection([
            RSegment("qcurve", [[int(i) for i in p] for p in pts], s.smooth)
            for s, pts in zip(self.instances, points)])


def fontsToQuadratic(fonts, compatible=False):
    """Convert the curves of a collection of fonts to quadratic.

    If compatibility is required, all curves will be converted to quadratic
    at once. Otherwise the glyphs will be converted one font at a time,
    which should be slightly more optimized.
    """

    if compatible:
        fonts = [FontCollection(fonts)]
    for font in fonts:
        for glyph in font:
            glyphCurvesToQuadratic(glyph)
