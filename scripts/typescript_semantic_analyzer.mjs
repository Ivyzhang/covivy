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
  let inBlockComment = false;
  const lines = source.split(/\r?\n/);
  lines.forEach((line, index) => {
    const lineNumber = index + 1;
    const trimmed = line.trim();
    if (!trimmed) {
      nonCodeLines.add(lineNumber);
      return;
    }
    if (inBlockComment) {
      nonCodeLines.add(lineNumber);
      if (trimmed.includes("*/")) {
        inBlockComment = false;
        const after = trimmed.split("*/", 2)[1].trim();
        if (after) nonCodeLines.delete(lineNumber);
      }
      return;
    }
    if (trimmed.startsWith("//")) {
      nonCodeLines.add(lineNumber);
      return;
    }
    const blockStart = line.indexOf("/*");
    if (blockStart !== -1) {
      const before = line.slice(0, blockStart).trim();
      const blockEnd = line.indexOf("*/", blockStart + 2);
      const after = blockEnd !== -1 ? line.slice(blockEnd + 2).trim() : "";
      if (!before && (blockEnd === -1 || !after)) nonCodeLines.add(lineNumber);
      if (blockEnd === -1) inBlockComment = true;
    }
  });
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
