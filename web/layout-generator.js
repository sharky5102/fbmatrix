(() => {
  'use strict';

  const TAU = Math.PI * 2;

  function guardGeometrySize(width, height, ledDistance, runCount) {
    const diagonal = Math.hypot(width, height);
    const estimatedPoints = runCount * 2 * (Math.ceil(diagonal / ledDistance) + 1);
    if (!Number.isFinite(estimatedPoints) || estimatedPoints > 100000) {
      throw new Error('These dimensions and LED spacing would create too many points');
    }
  }

  function normalizePoint(x, y, width, height, enabled, line, linePosition) {
    const scale = Math.max(width, height) / 2;
    return [x / scale, y / scale, 0, enabled, line, linePosition];
  }

  function generateRectangle(columns, rows) {
    const size = Math.min(2 / columns, 2 / rows);
    const yOffset = -(rows * size) / 2;
    const xOffset = -(columns * size) / 2;
    const points = [];
    for (let index = 0; index < columns * rows; index += 1) {
      const row = Math.floor(index / columns);
      const forward = row % 2 === 0;
      let column = index - row * columns;
      if (!forward) column = columns - 1 - column;
      points.push([
        xOffset + (column + 0.5) * size,
        yOffset + (row + 0.5) * size,
        0,
        1,
        row,
        columns > 1 ? column / (columns - 1) : 0,
      ]);
    }
    return points;
  }

  function rayRectangleIntersectionFrom(originX, originY, angle, width, height) {
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    const halfWidth = width / 2;
    const halfHeight = height / 2;
    const candidates = [];
    if (Math.abs(dx) > 1e-12) {
      const x = dx > 0 ? halfWidth : -halfWidth;
      const t = (x - originX) / dx;
      const y = originY + t * dy;
      if (t > 0 && y >= -halfHeight - 1e-9 && y <= halfHeight + 1e-9) {
        candidates.push([t, x, y]);
      }
    }
    if (Math.abs(dy) > 1e-12) {
      const y = dy > 0 ? halfHeight : -halfHeight;
      const t = (y - originY) / dy;
      const x = originX + t * dx;
      if (t > 0 && x >= -halfWidth - 1e-9 && x <= halfWidth + 1e-9) {
        candidates.push([t, x, y]);
      }
    }
    if (!candidates.length) throw new Error('Spoke does not intersect rectangle');
    candidates.sort((a, b) => a[0] - b[0]);
    return candidates[0];
  }

  function rayRectangleIntersection(angle, width, height) {
    return rayRectangleIntersectionFrom(0, 0, angle, width, height);
  }

  function edgeName(x, y, width, height) {
    if (Math.abs(x - width / 2) < 1e-8) return 'right';
    if (Math.abs(y - height / 2) < 1e-8) return 'top';
    if (Math.abs(x + width / 2) < 1e-8) return 'left';
    if (Math.abs(y + height / 2) < 1e-8) return 'bottom';
    throw new Error('Spoke endpoint is not on a rectangle edge');
  }

  function quarterName(x, y) {
    if (x >= 0 && y >= 0) return 'top-right';
    if (x < 0 && y >= 0) return 'top-left';
    if (x < 0 && y < 0) return 'bottom-left';
    return 'bottom-right';
  }

  function pointsOnSpoke(angle, edgeDistance, hubRadius, ledDistance,
      outward, line, width, height) {
    const count = Math.floor((edgeDistance - hubRadius) / ledDistance) + 1;
    let distances = Array.from({ length: count }, (_, index) => hubRadius + index * ledDistance);
    if (!outward) distances = distances.reverse();
    const extent = edgeDistance - hubRadius;
    return distances.map((distance) => normalizePoint(
      Math.cos(angle) * distance,
      Math.sin(angle) * distance,
      width,
      height,
      1,
      line,
      extent ? (distance - hubRadius) / extent : 0,
    ));
  }

  function pointsOnSegment(start, end, ledDistance, outward, line, width, height) {
    const dx0 = end[0] - start[0];
    const dy0 = end[1] - start[1];
    const distance = Math.hypot(dx0, dy0);
    if (distance <= 1e-12) throw new Error('Segment has no length');
    const count = Math.floor(distance / ledDistance) + 1;
    let offsets = Array.from({ length: count }, (_, index) => index * ledDistance);
    if (!outward) offsets = offsets.reverse();
    const dx = dx0 / distance;
    const dy = dy0 / distance;
    return offsets.map((offset) => normalizePoint(
      start[0] + dx * offset,
      start[1] + dy * offset,
      width,
      height,
      1,
      line,
      offset / distance,
    ));
  }

  function inactiveHopPoints(start, end, ledDistance, width, height) {
    const distance = Math.hypot(end[0] - start[0], end[1] - start[1]);
    const count = Math.floor(distance / ledDistance);
    return Array.from({ length: count }, (_, index) => {
      const t = (index + 1) / (count + 1);
      return normalizePoint(
        start[0] + (end[0] - start[0]) * t,
        start[1] + (end[1] - start[1]) * t,
        width,
        height,
        0,
        -1,
        0,
      );
    });
  }

  function finishFixedSection(section, sectionLeds, description) {
    if (section.length > sectionLeds) {
      throw new Error(`${description} needs ${section.length} LEDs, but section LEDs is ${sectionLeds}`);
    }
    while (section.length < sectionLeds) section.push([0, 0, 0, 0, -1, 0]);
    return section;
  }

  function generateRadial(width, height, ledDistance, hubRadius, spokes,
      sectionLeds, maxSpokeLength) {
    if (spokes % 8 !== 0) throw new Error('Radial layouts require spokes divisible by 8');
    if (width <= 0 || height <= 0) throw new Error('Width and height must be positive');
    if (ledDistance <= 0) throw new Error('LED spacing must be positive');
    if (hubRadius < 0) throw new Error('Hub radius cannot be negative');
    if (sectionLeds <= 0) throw new Error('Section LEDs must be positive');
    if (maxSpokeLength !== null && maxSpokeLength <= 0) throw new Error('Maximum spoke length must be positive');
    guardGeometrySize(width, height, ledDistance, spokes);

    const spacing = TAU / spokes;
    const firstAngle = spacing / 2;
    const spokeData = [];
    for (let index = 0; index < spokes; index += 1) {
      const angle = ((firstAngle - index * spacing) % TAU + TAU) % TAU;
      let [edgeDistance, edgeX, edgeY] = rayRectangleIntersection(angle, width, height);
      if (edgeDistance <= hubRadius) throw new Error(`Hub radius reaches beyond spoke ${index}`);
      const perimeterPoint = [edgeX, edgeY];
      const edge = edgeName(edgeX, edgeY, width, height);
      const hubPoint = [Math.cos(angle) * hubRadius, Math.sin(angle) * hubRadius];
      let activeLength = edgeDistance - hubRadius;
      if (maxSpokeLength !== null) {
        activeLength = Math.min(activeLength, maxSpokeLength);
        edgeDistance = hubRadius + activeLength;
        edgeX = Math.cos(angle) * edgeDistance;
        edgeY = Math.sin(angle) * edgeDistance;
      }
      spokeData.push({
        index, angle, edge, quarter: quarterName(edgeX, edgeY),
        edgePoint: [edgeX, edgeY], perimeterPoint, hubPoint, edgeDistance,
      });
    }

    const quarterOrder = ['top-left', 'top-right', 'bottom-right', 'bottom-left'];
    const points = [];
    quarterOrder.forEach((quarter, quarterIndex) => {
      const quarterSpokes = spokeData.filter((spoke) => spoke.quarter === quarter)
        .sort((a, b) => b.angle - a.angle);
      if (quarterSpokes.length < 4) {
        throw new Error(`Radial quarter ${quarter} needs at least 4 spokes`);
      }
      const splits = [];
      for (let split = 2; split < quarterSpokes.length; split += 2) splits.push(split);
      const split = splits.reduce((best, candidate) =>
        Math.abs(quarterSpokes.length - candidate * 2) < Math.abs(quarterSpokes.length - best * 2)
          ? candidate : best);
      [quarterSpokes.slice(0, split), quarterSpokes.slice(split)].forEach((sectionSpokes, halfIndex) => {
        if (sectionSpokes.length % 2) throw new Error(`Radial section ${quarter}/${halfIndex} needs an even spoke count`);
        const section = [];
        sectionSpokes.forEach((spoke, spokeIndex) => {
          const outward = spokeIndex % 2 === 0;
          section.push(...pointsOnSpoke(spoke.angle, spoke.edgeDistance, hubRadius,
            ledDistance, outward, spoke.index, width, height));
          if (spokeIndex + 1 < sectionSpokes.length) {
            const currentEnd = outward ? spoke.edgePoint : spoke.hubPoint;
            const nextSpoke = sectionSpokes[spokeIndex + 1];
            const nextOutward = (spokeIndex + 1) % 2 === 0;
            const nextStart = nextOutward ? nextSpoke.hubPoint : nextSpoke.edgePoint;
            section.push(...inactiveHopPoints(currentEnd, nextStart, ledDistance, width, height));
          }
        });
        points.push(...finishFixedSection(section, sectionLeds, `Radial section ${quarter}/${halfIndex}`));
      });
    });
    return points;
  }

  function clippedEndpoint(start, end, maxLength) {
    if (maxLength === null) return end;
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const distance = Math.hypot(dx, dy);
    if (distance <= maxLength || distance <= 1e-12) return end;
    const scale = maxLength / distance;
    return [start[0] + dx * scale, start[1] + dy * scale];
  }

  function median(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function dualRadialEdgeSpacing(spokes) {
    const spacings = [];
    for (let index = 1; index < spokes.length; index += 1) {
      const previous = spokes[index - 1];
      const current = spokes[index];
      if (previous.edge === current.edge) {
        spacings.push(Math.hypot(current.edgePoint[0] - previous.edgePoint[0],
          current.edgePoint[1] - previous.edgePoint[1]));
      }
    }
    return spacings;
  }

  function dualRadialSectionPoints(runs, ledDistance, width, height) {
    const section = [];
    runs.forEach((run, index) => {
      const outward = index % 2 === 0;
      section.push(...pointsOnSegment(run.start, run.end, ledDistance, outward,
        run.lineIndex, width, height));
      if (index + 1 < runs.length) {
        const currentEnd = outward ? run.end : run.start;
        const nextRun = runs[index + 1];
        const nextOutward = (index + 1) % 2 === 0;
        const nextStart = nextOutward ? nextRun.start : nextRun.end;
        section.push(...inactiveHopPoints(currentEnd, nextStart, ledDistance, width, height));
      }
    });
    return section;
  }

  function splitDualRadialPart(partName, runs, ledDistance, sectionLeds, width, height) {
    if (runs.length < 4 || runs.length % 2) {
      throw new Error(`Dual radial part ${partName} needs an even number of at least 4 runs`);
    }
    let best = null;
    for (let split = 2; split < runs.length; split += 2) {
      const first = dualRadialSectionPoints(runs.slice(0, split), ledDistance, width, height);
      const second = dualRadialSectionPoints(runs.slice(split), ledDistance, width, height);
      const score = Math.max(first.length, second.length);
      if (best === null || score < best.score) best = { score, split, sections: [first, second] };
    }
    const result = [];
    best.sections.forEach((section, index) => {
      result.push(...finishFixedSection(section, sectionLeds, `Dual radial section ${partName}/${index}`));
    });
    return result;
  }

  function roundTiesToEven(value) {
    const floor = Math.floor(value);
    const fraction = value - floor;
    if (fraction < 0.5) return floor;
    if (fraction > 0.5) return floor + 1;
    return floor % 2 === 0 ? floor : floor + 1;
  }

  function generateDualRadial(width, height, ledDistance, hubRadius, spokes,
      centerSpacing, sectionLeds, maxSpokeLength) {
    if (width <= 0 || height <= 0) throw new Error('Width and height must be positive');
    if (ledDistance <= 0) throw new Error('LED spacing must be positive');
    if (hubRadius < 0) throw new Error('Hub radius cannot be negative');
    if (centerSpacing < 0) throw new Error('Center spacing cannot be negative');
    if (centerSpacing === 0) {
      return generateRadial(width, height, ledDistance, hubRadius, spokes,
        sectionLeds, maxSpokeLength);
    }
    if (spokes % 4 !== 0) throw new Error('Dual radial spokes must be divisible by 4');
    if (centerSpacing + 2 * hubRadius >= width) {
      throw new Error('Center spacing plus two hub radii must be less than width');
    }
    if (sectionLeds <= 0) throw new Error('Section LEDs must be positive');
    if (maxSpokeLength !== null && maxSpokeLength <= 0) throw new Error('Maximum spoke length must be positive');
    guardGeometrySize(width, height, ledDistance, spokes * 2);

    const leftHub = [-centerSpacing / 2, 0];
    const rightHub = [centerSpacing / 2, 0];
    const sideSpokes = spokes / 2;
    const spacing = Math.PI / sideSpokes;
    const spokeSets = {
      'left-top': [], 'left-bottom': [], 'right-top': [], 'right-bottom': [],
    };
    for (let index = 0; index < sideSpokes; index += 1) {
      const leftAngle = Math.PI / 2 + spacing / 2 + index * spacing;
      const rightAngle = -Math.PI / 2 + spacing / 2 + index * spacing;
      [['left', leftHub, leftAngle], ['right', rightHub, rightAngle]].forEach(([side, hub, angle]) => {
        const [edgeDistance, edgeX, edgeY] = rayRectangleIntersectionFrom(
          hub[0], hub[1], angle, width, height);
        if (edgeDistance <= hubRadius) throw new Error(`Hub radius reaches beyond ${side} spoke ${index}`);
        const start = [hub[0] + Math.cos(angle) * hubRadius, hub[1] + Math.sin(angle) * hubRadius];
        const end = clippedEndpoint(start, [edgeX, edgeY], maxSpokeLength);
        const spoke = {
          kind: 'fan', edge: edgeName(edgeX, edgeY, width, height),
          edgePoint: [edgeX, edgeY], perimeterPoint: [edgeX, edgeY], start, end,
        };
        const half = edgeY >= 0 ? 'top' : 'bottom';
        spokeSets[`${side}-${half}`].push(spoke);
      });
    }

    const edgeSpacings = [];
    ['left', 'right'].forEach((side) => {
      edgeSpacings.push(...dualRadialEdgeSpacing(
        spokeSets[`${side}-top`].concat(spokeSets[`${side}-bottom`].slice().reverse())));
    });
    const centerLineSpacing = edgeSpacings.length ? median(edgeSpacings) : ledDistance;
    const centerStart = spokeSets['left-top'][0].edgePoint[0];
    const centerEnd = spokeSets['right-top'][spokeSets['right-top'].length - 1].edgePoint[0];
    const centerWidth = centerEnd - centerStart;
    let centerCount = Math.max(2, roundTiesToEven(centerWidth / centerLineSpacing) - 1);
    const desiredHalfOdd = (spokes / 4) % 2 === 1;
    if (centerCount % 2) centerCount += 1;
    if ((centerCount / 2) % 2 !== Number(desiredHalfOdd)) centerCount += 2;
    const centerXs = Array.from({ length: centerCount }, (_, index) =>
      centerStart + centerWidth * (index + 1) / (centerCount + 1));
    const leftXs = centerXs.slice(0, centerCount / 2);
    const rightXs = centerXs.slice(centerCount / 2);
    const centerRun = (x, y) => {
      const maxCenterLength = maxSpokeLength === null ? null : maxSpokeLength + hubRadius;
      return {
        kind: 'center', edge: y > 0 ? 'top' : 'bottom',
        edgePoint: [x, y], perimeterPoint: [x, y], start: [x, 0],
        end: clippedEndpoint([x, 0], [x, y], maxCenterLength),
      };
    };
    const partSpecs = [
      ['top-left', spokeSets['left-top'].slice().reverse().concat(leftXs.map((x) => centerRun(x, height / 2)))],
      ['top-right', rightXs.map((x) => centerRun(x, height / 2)).concat(spokeSets['right-top'].slice().reverse())],
      ['bottom-right', spokeSets['right-bottom'].slice().reverse().concat(rightXs.slice().reverse().map((x) => centerRun(x, -height / 2)))],
      ['bottom-left', leftXs.slice().reverse().map((x) => centerRun(x, -height / 2)).concat(spokeSets['left-bottom'].slice().reverse())],
    ];
    let lineIndex = 0;
    partSpecs.forEach(([, runs]) => runs.forEach((run) => { run.lineIndex = lineIndex++; }));
    const points = [];
    partSpecs.forEach(([name, runs]) => {
      points.push(...splitDualRadialPart(name, runs, ledDistance, sectionLeds, width, height));
    });
    return points;
  }

  function generateLayout(options) {
    let points;
    let stringLeds = options.stringLeds;
    if (options.type === 'rectangle') {
      if (!Number.isInteger(options.columns) || options.columns < 1 ||
          !Number.isInteger(options.rows) || options.rows < 1) {
        throw new Error('Columns and rows must be positive integers');
      }
      if (options.columns * options.rows > 28000) {
        throw new Error('Generated layout exceeds the 28000 LED limit');
      }
      points = generateRectangle(options.columns, options.rows);
      stringLeds = stringLeds || 500;
    } else {
      const sectionLeds = options.sectionLeds;
      if (sectionLeds > 500) throw new Error('Section LEDs cannot exceed 500');
      if (!stringLeds) stringLeds = Math.floor(500 / sectionLeds) * sectionLeds;
      if (stringLeds % sectionLeds) throw new Error('String LEDs must be a multiple of section LEDs');
      const maxLength = options.maxSpokeLength === '' ? null : options.maxSpokeLength;
      if (options.type === 'radial') {
        points = generateRadial(options.width, options.height, options.ledDistance,
          options.hubRadius, options.spokes, sectionLeds, maxLength);
      } else {
        points = generateDualRadial(options.width, options.height, options.ledDistance,
          options.hubRadius, options.spokes, options.centerSpacing, sectionLeds, maxLength);
      }
    }
    if (points.length > 28000) throw new Error('Generated layout exceeds the 28000 LED limit');
    if (!Number.isInteger(stringLeds) || stringLeds < 1 || stringLeds > 2000) {
      throw new Error('String LEDs must be between 1 and 2000');
    }
    const strings = [];
    for (let index = 0; index < points.length; index += stringLeds) {
      strings.push(points.slice(index, index + stringLeds));
    }
    if (strings.length > 14) throw new Error('Generated layout exceeds 14 output strings');
    return strings;
  }

  window.LayoutGenerator = { generateLayout };
})();
