import ts from "typescript";

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function scriptKind(path) {
  if (path.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (path.endsWith(".jsx")) return ts.ScriptKind.JSX;
  if (path.endsWith(".ts")) return ts.ScriptKind.TS;
  return ts.ScriptKind.JS;
}

function lineOf(sourceFile, position) {
  return sourceFile.getLineAndCharacterOfPosition(position).line + 1;
}

function lineSpan(sourceFile, node) {
  return {
    start: lineOf(sourceFile, node.getStart(sourceFile, false)),
    end: lineOf(sourceFile, node.getEnd()),
  };
}

function addRange(target, start, end) {
  for (let line = start; line <= end; line += 1) {
    target.add(line);
  }
}

function addCommentAndBlankLines(source, nonCodeLines) {
  const lines = source.split(/\r?\n/);

  // Build line-start offsets for mapping character positions to line numbers
  const lineStarts = [];
  let off = 0;
  for (const line of lines) {
    lineStarts.push(off);
    off += line.length + 1;
  }

  function lineOfPos(offset) {
    let lo = 0, hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid] <= offset) lo = mid;
      else hi = mid - 1;
    }
    return lo + 1;
  }

  // Mark blank lines
  lines.forEach((line, i) => {
    if (!line.trim()) nonCodeLines.add(i + 1);
  });

  // Use TypeScript's scanner to find comment tokens. skipTrivia=false is
  // required so that comment tokens are returned; without it the scanner
  // silently skips them. Using the scanner (rather than indexOf) correctly
  // ignores "/*" or "*/" that appear inside string/template literals or
  // regular expressions, preventing false inBlockComment flips.
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, /* skipTrivia */ false);
  scanner.setText(source);
  const codeLines = new Set();
  let kind;
  while ((kind = scanner.scan()) !== ts.SyntaxKind.EndOfFileToken) {
    if (
      kind === ts.SyntaxKind.SingleLineCommentTrivia ||
      kind === ts.SyntaxKind.MultiLineCommentTrivia
    ) {
      const startLine = lineOfPos(scanner.getTokenStart());
      const endLine = lineOfPos(scanner.getTokenEnd() - 1);
      for (let l = startLine; l <= endLine; l++) {
        if (!codeLines.has(l)) nonCodeLines.add(l);
      }
    } else if (
      kind !== ts.SyntaxKind.WhitespaceTrivia &&
      kind !== ts.SyntaxKind.NewLineTrivia
    ) {
      const l = lineOfPos(scanner.getTokenStart());
      codeLines.add(l);
      nonCodeLines.delete(l);
    }
  }
}

function isTypeOnlyImport(node) {
  if (!ts.isImportDeclaration(node)) return false;
  if (!node.importClause) return false;
  return node.importClause.isTypeOnly;
}

function isTypeOnlyExport(node) {
  if (!ts.isExportDeclaration(node)) return false;
  return node.isTypeOnly;
}

function hasDeclareModifier(node) {
  return Boolean(
    node.modifiers &&
      node.modifiers.some(modifier => modifier.kind === ts.SyntaxKind.DeclareKeyword)
  );
}

function isInAmbientDeclaration(node) {
  let current = node;
  while (current) {
    if (hasDeclareModifier(current)) return true;
    current = current.parent;
  }
  return false;
}

function isNonRuntimeDeclaration(node) {
  return (
    ts.isInterfaceDeclaration(node) ||
    ts.isTypeAliasDeclaration(node) ||
    (ts.isModuleDeclaration(node) && hasDeclareModifier(node)) ||
    (ts.isEnumMember(node) && isInAmbientDeclaration(node)) ||
    isTypeOnlyImport(node) ||
    isTypeOnlyExport(node)
  );
}

function isCoverageUnit(node) {
  return (
    ts.isImportDeclaration(node) ||
    ts.isModuleDeclaration(node) ||
    ts.isEnumMember(node) ||
    ts.isExpressionStatement(node) ||
    ts.isReturnStatement(node) ||
    ts.isVariableDeclaration(node) ||
    ts.isVariableStatement(node) ||
    ts.isIfStatement(node) ||
    ts.isForStatement(node) ||
    ts.isForOfStatement(node) ||
    ts.isForInStatement(node) ||
    ts.isWhileStatement(node) ||
    ts.isDoStatement(node) ||
    ts.isSwitchStatement(node) ||
    ts.isThrowStatement(node) ||
    ts.isTryStatement(node) ||
    ts.isWithStatement(node)
  );
}

function nearestCoverageUnit(node) {
  let current = node;
  while (current) {
    if (isCoverageUnit(current)) return current;
    if (
      ts.isFunctionDeclaration(current) ||
      ts.isFunctionExpression(current) ||
      ts.isArrowFunction(current) ||
      ts.isClassDeclaration(current) ||
      ts.isSourceFile(current)
    ) {
      return undefined;
    }
    current = current.parent;
  }
  return undefined;
}

function walk(node, visit) {
  visit(node);
  node.forEachChild(child => walk(child, visit));
}

function analyze(payload) {
  const sourceFile = ts.createSourceFile(
    payload.path || "source.ts",
    payload.source || "",
    ts.ScriptTarget.Latest,
    true,
    scriptKind(payload.path || "")
  );
  const changedLines = new Set((payload.changedLines || []).map(Number));
  const hitsByLine = new Map(
    Object.entries(payload.hitsByLine || {}).map(([line, hits]) => [Number(line), Number(hits)])
  );
  const nonCodeLines = new Set();
  const nodeByLine = new Map();

  addCommentAndBlankLines(payload.source || "", nonCodeLines);

  walk(sourceFile, node => {
    const span = lineSpan(sourceFile, node);
    if (isNonRuntimeDeclaration(node)) {
      addRange(nonCodeLines, span.start, span.end);
    }
    if (!isCoverageUnit(node)) return;
    for (let line = span.start; line <= span.end; line++) {
      if (!changedLines.has(line)) continue;
      const previous = nodeByLine.get(line);
      if (!previous) {
        nodeByLine.set(line, node);
        continue;
      }
      const previousSpan = lineSpan(sourceFile, previous);
      if (
        span.end - span.start < previousSpan.end - previousSpan.start ||
        (span.end - span.start === previousSpan.end - previousSpan.start &&
          node.getWidth(sourceFile) < previous.getWidth(sourceFile))
      ) {
        nodeByLine.set(line, node);
      }
    }
  });

  const lineDecisions = {};
  for (const line of changedLines) {
    const node = nodeByLine.get(line);
    if (!node) continue;
    const unit = nearestCoverageUnit(node);
    if (!unit) continue;
    const span = lineSpan(sourceFile, unit);
    const hits = [];
    for (const [hitLine, count] of hitsByLine.entries()) {
      if (span.start <= hitLine && hitLine <= span.end) hits.push(count);
    }
    if (hits.length > 0) {
      lineDecisions[String(line)] = hits.some(count => count > 0);
    }
  }

  return {
    nonCodeLines: [...nonCodeLines].sort((a, b) => a - b),
    lineDecisions,
  };
}

try {
  const input = JSON.parse(await readStdin());
  process.stdout.write(JSON.stringify(analyze(input)));
} catch (error) {
  process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
  process.exit(1);
}
