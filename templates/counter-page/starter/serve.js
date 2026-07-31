// Static server used by the checks. Provided as a starter file so the task needs no package
// installation — and so every model finds exactly the same serving environment. A
// self-built server per model would be an uncontrolled variable.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const PORT = 5173;
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
};

http
  .createServer((request, response) => {
    const url = (request.url || "/").split("?")[0];
    const relative = url === "/" ? "index.html" : url.replace(/^\/+/, "");
    const target = path.join(process.cwd(), relative);

    // No escaping the working directory via ../
    if (!target.startsWith(process.cwd())) {
      response.statusCode = 403;
      response.end("forbidden");
      return;
    }

    fs.readFile(target, (error, data) => {
      if (error) {
        response.statusCode = 404;
        response.end("not found");
        return;
      }
      response.setHeader("Content-Type", TYPES[path.extname(target)] || "text/plain");
      response.end(data);
    });
  })
  .listen(PORT, "0.0.0.0", () => {
    console.log(`serve.js listening on ${PORT}`);
  });
