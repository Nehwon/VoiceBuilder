// Mode CodeMirror « tagged » : surligne les préfixes [Nom]: et les tags inline.
CodeMirror.defineMode("tagged", function () {
  return {
    token: function (stream) {
      var ch = stream.next();
      if (ch === "[") {
        stream.eatWhile(/[^\]\n]/);
        if (stream.peek() === "]") stream.next();
        return "property";
      }
      if (ch === ":") return "operator";
      stream.eatWhile(/[^[\n]/);
      return null;
    },
  };
});
CodeMirror.defineMIME("text/x-tagged", "tagged");