"use strict";
var VerifyArticleStructure = (() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));
  var __objRest = (source, exclude) => {
    var target = {};
    for (var prop in source)
      if (__hasOwnProp.call(source, prop) && exclude.indexOf(prop) < 0)
        target[prop] = source[prop];
    if (source != null && __getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(source)) {
        if (exclude.indexOf(prop) < 0 && __propIsEnum.call(source, prop))
          target[prop] = source[prop];
      }
    return target;
  };
  var __commonJS = (cb, mod) => function __require() {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);
  var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);
  var __async = (__this, __arguments, generator) => {
    return new Promise((resolve, reject) => {
      var fulfilled = (value) => {
        try {
          step(generator.next(value));
        } catch (e) {
          reject(e);
        }
      };
      var rejected = (value) => {
        try {
          step(generator.throw(value));
        } catch (e) {
          reject(e);
        }
      };
      var step = (x) => x.done ? resolve(x.value) : Promise.resolve(x.value).then(fulfilled, rejected);
      step((generator = generator.apply(__this, __arguments)).next());
    });
  };

  // node_modules/mp-darkmode/dist/darkmode.min.js
  var require_darkmode_min = __commonJS({
    "node_modules/mp-darkmode/dist/darkmode.min.js"(exports, module) {
      !function(e, t) {
        "object" == typeof exports && "object" == typeof module ? module.exports = t() : "function" == typeof define && define.amd ? define("Darkmode", [], t) : "object" == typeof exports ? exports.Darkmode = t() : e.Darkmode = t();
      }(self, () => (() => {
        var e = { 41(e2, t2, r2) {
          "use strict";
          var n2 = r2(655), o = r2(8068), a = r2(9675), i = r2(5795);
          e2.exports = function(e3, t3, r3) {
            if (!e3 || "object" != typeof e3 && "function" != typeof e3) throw new a("`obj` must be an object or a function`");
            if ("string" != typeof t3 && "symbol" != typeof t3) throw new a("`property` must be a string or a symbol`");
            if (arguments.length > 3 && "boolean" != typeof arguments[3] && null !== arguments[3]) throw new a("`nonEnumerable`, if provided, must be a boolean or null");
            if (arguments.length > 4 && "boolean" != typeof arguments[4] && null !== arguments[4]) throw new a("`nonWritable`, if provided, must be a boolean or null");
            if (arguments.length > 5 && "boolean" != typeof arguments[5] && null !== arguments[5]) throw new a("`nonConfigurable`, if provided, must be a boolean or null");
            if (arguments.length > 6 && "boolean" != typeof arguments[6]) throw new a("`loose`, if provided, must be a boolean");
            var s = arguments.length > 3 ? arguments[3] : null, l = arguments.length > 4 ? arguments[4] : null, c = arguments.length > 5 ? arguments[5] : null, u = arguments.length > 6 && arguments[6], h = !!i && i(e3, t3);
            if (n2) n2(e3, t3, { configurable: null === c && h ? h.configurable : !c, enumerable: null === s && h ? h.enumerable : !s, value: r3, writable: null === l && h ? h.writable : !l });
            else {
              if (!u && (s || l || c)) throw new o("This environment does not support defining a property as non-configurable, non-writable, or non-enumerable.");
              e3[t3] = r3;
            }
          };
        }, 76(e2) {
          "use strict";
          e2.exports = Function.prototype.call;
        }, 162(e2) {
          "use strict";
          e2.exports = function(e3) {
            return null === e3 || "function" != typeof e3 && "object" != typeof e3;
          };
        }, 296(e2, t2, r2) {
          "use strict";
          var n2 = r2(3348), o = r2(855), a = r2(2491);
          e2.exports = function(e3, t3) {
            var r3 = n2(e3), i = o(t3);
            return a(r3, i);
          };
        }, 414(e2) {
          "use strict";
          e2.exports = Math.round;
        }, 453(e2, t2, r2) {
          "use strict";
          var n2, o = r2(9612), a = r2(9383), i = r2(1237), s = r2(9290), l = r2(9538), c = r2(8068), u = r2(9675), h = r2(5345), f = r2(1514), p = r2(8968), d = r2(6188), g = r2(8002), m = r2(5880), b = r2(414), y = r2(3093), w = Function, v = function(e3) {
            try {
              return w('"use strict"; return (' + e3 + ").constructor;")();
            } catch (e4) {
            }
          }, k = r2(5795), _ = r2(655), M = function() {
            throw new u();
          }, S = k ? function() {
            try {
              return M;
            } catch (e3) {
              try {
                return k(arguments, "callee").get;
              } catch (e4) {
                return M;
              }
            }
          }() : M, E = r2(4039)(), C = r2(3628), x = r2(1064), O = r2(8648), j = r2(1002), R = r2(76), A = {}, T = "undefined" != typeof Uint8Array && C ? C(Uint8Array) : n2, B = { __proto__: null, "%AggregateError%": "undefined" == typeof AggregateError ? n2 : AggregateError, "%Array%": Array, "%ArrayBuffer%": "undefined" == typeof ArrayBuffer ? n2 : ArrayBuffer, "%ArrayIteratorPrototype%": E && C ? C([][Symbol.iterator]()) : n2, "%AsyncFromSyncIteratorPrototype%": n2, "%AsyncFunction%": A, "%AsyncGenerator%": A, "%AsyncGeneratorFunction%": A, "%AsyncIteratorPrototype%": A, "%Atomics%": "undefined" == typeof Atomics ? n2 : Atomics, "%BigInt%": "undefined" == typeof BigInt ? n2 : BigInt, "%BigInt64Array%": "undefined" == typeof BigInt64Array ? n2 : BigInt64Array, "%BigUint64Array%": "undefined" == typeof BigUint64Array ? n2 : BigUint64Array, "%Boolean%": Boolean, "%DataView%": "undefined" == typeof DataView ? n2 : DataView, "%Date%": Date, "%decodeURI%": decodeURI, "%decodeURIComponent%": decodeURIComponent, "%encodeURI%": encodeURI, "%encodeURIComponent%": encodeURIComponent, "%Error%": a, "%eval%": eval, "%EvalError%": i, "%Float16Array%": "undefined" == typeof Float16Array ? n2 : Float16Array, "%Float32Array%": "undefined" == typeof Float32Array ? n2 : Float32Array, "%Float64Array%": "undefined" == typeof Float64Array ? n2 : Float64Array, "%FinalizationRegistry%": "undefined" == typeof FinalizationRegistry ? n2 : FinalizationRegistry, "%Function%": w, "%GeneratorFunction%": A, "%Int8Array%": "undefined" == typeof Int8Array ? n2 : Int8Array, "%Int16Array%": "undefined" == typeof Int16Array ? n2 : Int16Array, "%Int32Array%": "undefined" == typeof Int32Array ? n2 : Int32Array, "%isFinite%": isFinite, "%isNaN%": isNaN, "%IteratorPrototype%": E && C ? C(C([][Symbol.iterator]())) : n2, "%JSON%": "object" == typeof JSON ? JSON : n2, "%Map%": "undefined" == typeof Map ? n2 : Map, "%MapIteratorPrototype%": "undefined" != typeof Map && E && C ? C((/* @__PURE__ */ new Map())[Symbol.iterator]()) : n2, "%Math%": Math, "%Number%": Number, "%Object%": o, "%Object.getOwnPropertyDescriptor%": k, "%parseFloat%": parseFloat, "%parseInt%": parseInt, "%Promise%": "undefined" == typeof Promise ? n2 : Promise, "%Proxy%": "undefined" == typeof Proxy ? n2 : Proxy, "%RangeError%": s, "%ReferenceError%": l, "%Reflect%": "undefined" == typeof Reflect ? n2 : Reflect, "%RegExp%": RegExp, "%Set%": "undefined" == typeof Set ? n2 : Set, "%SetIteratorPrototype%": "undefined" != typeof Set && E && C ? C((/* @__PURE__ */ new Set())[Symbol.iterator]()) : n2, "%SharedArrayBuffer%": "undefined" == typeof SharedArrayBuffer ? n2 : SharedArrayBuffer, "%String%": String, "%StringIteratorPrototype%": E && C ? C(""[Symbol.iterator]()) : n2, "%Symbol%": E ? Symbol : n2, "%SyntaxError%": c, "%ThrowTypeError%": S, "%TypedArray%": T, "%TypeError%": u, "%Uint8Array%": "undefined" == typeof Uint8Array ? n2 : Uint8Array, "%Uint8ClampedArray%": "undefined" == typeof Uint8ClampedArray ? n2 : Uint8ClampedArray, "%Uint16Array%": "undefined" == typeof Uint16Array ? n2 : Uint16Array, "%Uint32Array%": "undefined" == typeof Uint32Array ? n2 : Uint32Array, "%URIError%": h, "%WeakMap%": "undefined" == typeof WeakMap ? n2 : WeakMap, "%WeakRef%": "undefined" == typeof WeakRef ? n2 : WeakRef, "%WeakSet%": "undefined" == typeof WeakSet ? n2 : WeakSet, "%Function.prototype.call%": R, "%Function.prototype.apply%": j, "%Object.defineProperty%": _, "%Object.getPrototypeOf%": x, "%Math.abs%": f, "%Math.floor%": p, "%Math.max%": d, "%Math.min%": g, "%Math.pow%": m, "%Math.round%": b, "%Math.sign%": y, "%Reflect.getPrototypeOf%": O };
          if (C) try {
            null.error;
          } catch (e3) {
            var P = C(C(e3));
            B["%Error.prototype%"] = P;
          }
          var N = function e3(t3) {
            var r3;
            if ("%AsyncFunction%" === t3) r3 = v("async function () {}");
            else if ("%GeneratorFunction%" === t3) r3 = v("function* () {}");
            else if ("%AsyncGeneratorFunction%" === t3) r3 = v("async function* () {}");
            else if ("%AsyncGenerator%" === t3) {
              var n3 = e3("%AsyncGeneratorFunction%");
              n3 && (r3 = n3.prototype);
            } else if ("%AsyncIteratorPrototype%" === t3) {
              var o2 = e3("%AsyncGenerator%");
              o2 && C && (r3 = C(o2.prototype));
            }
            return B[t3] = r3, r3;
          }, L = { __proto__: null, "%ArrayBufferPrototype%": ["ArrayBuffer", "prototype"], "%ArrayPrototype%": ["Array", "prototype"], "%ArrayProto_entries%": ["Array", "prototype", "entries"], "%ArrayProto_forEach%": ["Array", "prototype", "forEach"], "%ArrayProto_keys%": ["Array", "prototype", "keys"], "%ArrayProto_values%": ["Array", "prototype", "values"], "%AsyncFunctionPrototype%": ["AsyncFunction", "prototype"], "%AsyncGenerator%": ["AsyncGeneratorFunction", "prototype"], "%AsyncGeneratorPrototype%": ["AsyncGeneratorFunction", "prototype", "prototype"], "%BooleanPrototype%": ["Boolean", "prototype"], "%DataViewPrototype%": ["DataView", "prototype"], "%DatePrototype%": ["Date", "prototype"], "%ErrorPrototype%": ["Error", "prototype"], "%EvalErrorPrototype%": ["EvalError", "prototype"], "%Float32ArrayPrototype%": ["Float32Array", "prototype"], "%Float64ArrayPrototype%": ["Float64Array", "prototype"], "%FunctionPrototype%": ["Function", "prototype"], "%Generator%": ["GeneratorFunction", "prototype"], "%GeneratorPrototype%": ["GeneratorFunction", "prototype", "prototype"], "%Int8ArrayPrototype%": ["Int8Array", "prototype"], "%Int16ArrayPrototype%": ["Int16Array", "prototype"], "%Int32ArrayPrototype%": ["Int32Array", "prototype"], "%JSONParse%": ["JSON", "parse"], "%JSONStringify%": ["JSON", "stringify"], "%MapPrototype%": ["Map", "prototype"], "%NumberPrototype%": ["Number", "prototype"], "%ObjectPrototype%": ["Object", "prototype"], "%ObjProto_toString%": ["Object", "prototype", "toString"], "%ObjProto_valueOf%": ["Object", "prototype", "valueOf"], "%PromisePrototype%": ["Promise", "prototype"], "%PromiseProto_then%": ["Promise", "prototype", "then"], "%Promise_all%": ["Promise", "all"], "%Promise_reject%": ["Promise", "reject"], "%Promise_resolve%": ["Promise", "resolve"], "%RangeErrorPrototype%": ["RangeError", "prototype"], "%ReferenceErrorPrototype%": ["ReferenceError", "prototype"], "%RegExpPrototype%": ["RegExp", "prototype"], "%SetPrototype%": ["Set", "prototype"], "%SharedArrayBufferPrototype%": ["SharedArrayBuffer", "prototype"], "%StringPrototype%": ["String", "prototype"], "%SymbolPrototype%": ["Symbol", "prototype"], "%SyntaxErrorPrototype%": ["SyntaxError", "prototype"], "%TypedArrayPrototype%": ["TypedArray", "prototype"], "%TypeErrorPrototype%": ["TypeError", "prototype"], "%Uint8ArrayPrototype%": ["Uint8Array", "prototype"], "%Uint8ClampedArrayPrototype%": ["Uint8ClampedArray", "prototype"], "%Uint16ArrayPrototype%": ["Uint16Array", "prototype"], "%Uint32ArrayPrototype%": ["Uint32Array", "prototype"], "%URIErrorPrototype%": ["URIError", "prototype"], "%WeakMapPrototype%": ["WeakMap", "prototype"], "%WeakSetPrototype%": ["WeakSet", "prototype"] }, D = r2(6743), F = r2(9957), I = D.call(R, Array.prototype.concat), $ = D.call(j, Array.prototype.splice), z = D.call(R, String.prototype.replace), q = D.call(R, String.prototype.slice), H = D.call(R, RegExp.prototype.exec), W = /[^%.[\]]+|\[(?:(-?\d+(?:\.\d+)?)|(["'])((?:(?!\2)[^\\]|\\.)*?)\2)\]|(?=(?:\.|\[\])(?:\.|\[\]|%$))/g, G = /\\(\\)?/g, Y = function(e3, t3) {
            var r3, n3 = e3;
            if (F(L, n3) && (n3 = "%" + (r3 = L[n3])[0] + "%"), F(B, n3)) {
              var o2 = B[n3];
              if (o2 === A && (o2 = N(n3)), void 0 === o2 && !t3) throw new u("intrinsic " + e3 + " exists, but is not available. Please file an issue!");
              return { alias: r3, name: n3, value: o2 };
            }
            throw new c("intrinsic " + e3 + " does not exist!");
          };
          e2.exports = function(e3, t3) {
            if ("string" != typeof e3 || 0 === e3.length) throw new u("intrinsic name must be a non-empty string");
            if (arguments.length > 1 && "boolean" != typeof t3) throw new u('"allowMissing" argument must be a boolean');
            if (null === H(/^%?[^%]*%?$/, e3)) throw new c("`%` may not be present anywhere but at the beginning and end of the intrinsic name");
            var r3 = function(e4) {
              var t4 = q(e4, 0, 1), r4 = q(e4, -1);
              if ("%" === t4 && "%" !== r4) throw new c("invalid intrinsic syntax, expected closing `%`");
              if ("%" === r4 && "%" !== t4) throw new c("invalid intrinsic syntax, expected opening `%`");
              var n4 = [];
              return z(e4, W, function(e5, t5, r5, o3) {
                n4[n4.length] = r5 ? z(o3, G, "$1") : t5 || e5;
              }), n4;
            }(e3), n3 = r3.length > 0 ? r3[0] : "", o2 = Y("%" + n3 + "%", t3), a2 = o2.name, i2 = o2.value, s2 = false, l2 = o2.alias;
            l2 && (n3 = l2[0], $(r3, I([0, 1], l2)));
            for (var h2 = 1, f2 = true; h2 < r3.length; h2 += 1) {
              var p2 = r3[h2], d2 = q(p2, 0, 1), g2 = q(p2, -1);
              if (('"' === d2 || "'" === d2 || "`" === d2 || '"' === g2 || "'" === g2 || "`" === g2) && d2 !== g2) throw new c("property names with quotes must have matching quotes");
              if ("constructor" !== p2 && f2 || (s2 = true), F(B, a2 = "%" + (n3 += "." + p2) + "%")) i2 = B[a2];
              else if (null != i2) {
                if (!(p2 in i2)) {
                  if (!t3) throw new u("base intrinsic for " + e3 + " exists, but the property is not available.");
                  return;
                }
                if (k && h2 + 1 >= r3.length) {
                  var m2 = k(i2, p2);
                  i2 = (f2 = !!m2) && "get" in m2 && !("originalValue" in m2.get) ? m2.get : i2[p2];
                } else f2 = F(i2, p2), i2 = i2[p2];
                f2 && !s2 && (B[a2] = i2);
              }
            }
            return i2;
          };
        }, 592(e2, t2, r2) {
          "use strict";
          var n2 = r2(655), o = function() {
            return !!n2;
          };
          o.hasArrayLengthDefineBug = function() {
            if (!n2) return null;
            try {
              return 1 !== n2([], "length", { value: 1 }).length;
            } catch (e3) {
              return true;
            }
          }, e2.exports = o;
        }, 655(e2) {
          "use strict";
          var t2 = Object.defineProperty || false;
          if (t2) try {
            t2({}, "a", { value: 1 });
          } catch (e3) {
            t2 = false;
          }
          e2.exports = t2;
        }, 855(e2, t2, r2) {
          "use strict";
          var n2 = r2(453)("%String%"), o = r2(866), a = r2(4810);
          e2.exports = function(e3) {
            var t3 = o(e3, n2);
            return "symbol" == typeof t3 ? t3 : a(t3);
          };
        }, 866(e2, t2, r2) {
          "use strict";
          var n2 = r2(5437);
          e2.exports = function(e3) {
            return arguments.length > 1 ? n2(e3, arguments[1]) : n2(e3);
          };
        }, 1002(e2) {
          "use strict";
          e2.exports = Function.prototype.apply;
        }, 1064(e2, t2, r2) {
          "use strict";
          var n2 = r2(9612);
          e2.exports = n2.getPrototypeOf || null;
        }, 1067(e2, t2, r2) {
          "use strict";
          var n2 = r2(4541), o = r2(8452);
          e2.exports = function() {
            var e3 = n2();
            return o(Object, { hasOwn: e3 }, { hasOwn: function() {
              return Object.hasOwn !== e3;
            } }), e3;
          };
        }, 1093(e2) {
          "use strict";
          var t2 = Object.prototype.toString;
          e2.exports = function(e3) {
            var r2 = t2.call(e3), n2 = "[object Arguments]" === r2;
            return n2 || (n2 = "[object Array]" !== r2 && null !== e3 && "object" == typeof e3 && "number" == typeof e3.length && e3.length >= 0 && "[object Function]" === t2.call(e3.callee)), n2;
          };
        }, 1189(e2, t2, r2) {
          "use strict";
          var n2 = Array.prototype.slice, o = r2(1093), a = Object.keys, i = a ? function(e3) {
            return a(e3);
          } : r2(8875), s = Object.keys;
          i.shim = function() {
            if (Object.keys) {
              var e3 = function() {
                var e4 = Object.keys(arguments);
                return e4 && e4.length === arguments.length;
              }(1, 2);
              e3 || (Object.keys = function(e4) {
                return o(e4) ? s(n2.call(e4)) : s(e4);
              });
            } else Object.keys = i;
            return Object.keys || i;
          }, e2.exports = i;
        }, 1237(e2) {
          "use strict";
          e2.exports = EvalError;
        }, 1333(e2) {
          "use strict";
          e2.exports = function() {
            if ("function" != typeof Symbol || "function" != typeof Object.getOwnPropertySymbols) return false;
            if ("symbol" == typeof Symbol.iterator) return true;
            var e3 = {}, t2 = Symbol("test"), r2 = Object(t2);
            if ("string" == typeof t2) return false;
            if ("[object Symbol]" !== Object.prototype.toString.call(t2)) return false;
            if ("[object Symbol]" !== Object.prototype.toString.call(r2)) return false;
            for (var n2 in e3[t2] = 42, e3) return false;
            if ("function" == typeof Object.keys && 0 !== Object.keys(e3).length) return false;
            if ("function" == typeof Object.getOwnPropertyNames && 0 !== Object.getOwnPropertyNames(e3).length) return false;
            var o = Object.getOwnPropertySymbols(e3);
            if (1 !== o.length || o[0] !== t2) return false;
            if (!Object.prototype.propertyIsEnumerable.call(e3, t2)) return false;
            if ("function" == typeof Object.getOwnPropertyDescriptor) {
              var a = Object.getOwnPropertyDescriptor(e3, t2);
              if (42 !== a.value || true !== a.enumerable) return false;
            }
            return true;
          };
        }, 1514(e2) {
          "use strict";
          e2.exports = Math.abs;
        }, 2120(e2, t2, r2) {
          "use strict";
          var n2 = r2(6556), o = n2("Date.prototype.getDay"), a = n2("Object.prototype.toString"), i = r2(9092)();
          e2.exports = function(e3) {
            return "object" == typeof e3 && null !== e3 && (i ? function(e4) {
              try {
                return o(e4), true;
              } catch (e5) {
                return false;
              }
            }(e3) : "[object Date]" === a(e3));
          };
        }, 2491(e2, t2, r2) {
          "use strict";
          var n2 = r2(9675), o = r2(9957), a = r2(6537), i = r2(3541);
          e2.exports = function(e3, t3) {
            if (!a(e3)) throw new n2("Assertion failed: `O` must be an Object");
            if (!i(t3)) throw new n2("Assertion failed: `P` must be a Property Key");
            return o(e3, t3);
          };
        }, 2634() {
        }, 3093(e2, t2, r2) {
          "use strict";
          var n2 = r2(4459);
          e2.exports = function(e3) {
            return n2(e3) || 0 === e3 ? e3 : e3 < 0 ? -1 : 1;
          };
        }, 3118(e2, t2, r2) {
          "use strict";
          var n2 = r2(9675), o = r2(9600), a = r2(8859), i = r2(9705), s = r2(9487);
          e2.exports = function(e3, t3) {
            if (!s(t3)) throw new n2("Assertion failed: P is not a Property Key");
            var r3 = i(e3, t3);
            if (null != r3) {
              if (!o(r3)) throw new n2(a(t3) + " is not a function: " + a(r3));
              return r3;
            }
          };
        }, 3126(e2, t2, r2) {
          "use strict";
          var n2 = r2(6743), o = r2(9675), a = r2(76), i = r2(3144);
          e2.exports = function(e3) {
            if (e3.length < 1 || "function" != typeof e3[0]) throw new o("a function is required");
            return i(n2, a, e3);
          };
        }, 3144(e2, t2, r2) {
          "use strict";
          var n2 = r2(6743), o = r2(1002), a = r2(76), i = r2(7119);
          e2.exports = i || n2.call(a, o);
        }, 3348(e2, t2, r2) {
          "use strict";
          var n2 = r2(9612), o = r2(5388);
          e2.exports = function(e3) {
            return o(e3), n2(e3);
          };
        }, 3541(e2) {
          "use strict";
          e2.exports = function(e3) {
            return "string" == typeof e3 || "symbol" == typeof e3;
          };
        }, 3612(e2, t2, r2) {
          "use strict";
          var n2 = r2(6556), o = n2("Object.prototype.toString"), a = r2(4039)(), i = r2(9721);
          if (a) {
            var s = n2("Symbol.prototype.toString"), l = i(/^Symbol\(.*\)$/);
            e2.exports = function(e3) {
              if ("symbol" == typeof e3) return true;
              if (!e3 || "object" != typeof e3 || "[object Symbol]" !== o(e3)) return false;
              try {
                return function(e4) {
                  return "symbol" == typeof e4.valueOf() && l(s(e4));
                }(e3);
              } catch (e4) {
                return false;
              }
            };
          } else e2.exports = function(e3) {
            return false;
          };
        }, 3628(e2, t2, r2) {
          "use strict";
          var n2 = r2(8648), o = r2(1064), a = r2(7176);
          e2.exports = n2 ? function(e3) {
            return n2(e3);
          } : o ? function(e3) {
            if (!e3 || "object" != typeof e3 && "function" != typeof e3) throw new TypeError("getProto: not an object");
            return o(e3);
          } : a ? function(e3) {
            return a(e3);
          } : null;
        }, 4035(e2, t2, r2) {
          "use strict";
          var n2, o = r2(6556), a = r2(9092)(), i = r2(9957), s = r2(5795);
          if (a) {
            var l = o("RegExp.prototype.exec"), c = {}, u = function() {
              throw c;
            }, h = { toString: u, valueOf: u };
            "symbol" == typeof Symbol.toPrimitive && (h[Symbol.toPrimitive] = u), n2 = function(e3) {
              if (!e3 || "object" != typeof e3) return false;
              var t3 = s(e3, "lastIndex");
              if (!t3 || !i(t3, "value")) return false;
              try {
                l(e3, h);
              } catch (e4) {
                return e4 === c;
              }
            };
          } else {
            var f = o("Object.prototype.toString");
            n2 = function(e3) {
              return !(!e3 || "object" != typeof e3 && "function" != typeof e3) && "[object RegExp]" === f(e3);
            };
          }
          e2.exports = n2;
        }, 4039(e2, t2, r2) {
          "use strict";
          var n2 = "undefined" != typeof Symbol && Symbol, o = r2(1333);
          e2.exports = function() {
            return "function" == typeof n2 && "function" == typeof Symbol && "symbol" == typeof n2("foo") && "symbol" == typeof Symbol("bar") && o();
          };
        }, 4459(e2) {
          "use strict";
          e2.exports = Number.isNaN || function(e3) {
            return e3 != e3;
          };
        }, 4541(e2, t2, r2) {
          "use strict";
          var n2 = r2(296);
          e2.exports = function() {
            return Object.hasOwn || n2;
          };
        }, 4810(e2, t2, r2) {
          "use strict";
          var n2 = r2(453)("%String%"), o = r2(9675);
          e2.exports = function(e3) {
            if ("symbol" == typeof e3) throw new o("Cannot convert a Symbol value to a string");
            return n2(e3);
          };
        }, 5345(e2) {
          "use strict";
          e2.exports = URIError;
        }, 5388(e2, t2, r2) {
          "use strict";
          var n2 = r2(9675);
          e2.exports = function(e3) {
            if (null == e3) throw new n2(arguments.length > 0 && arguments[1] || "Cannot call method on " + e3);
            return e3;
          };
        }, 5437(e2, t2, r2) {
          "use strict";
          var n2 = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator, o = r2(9600), a = r2(2120), i = r2(3612), s = r2(9675), l = r2(162), c = r2(3118);
          e2.exports = function(e3) {
            if (l(e3)) return e3;
            var t3, r3 = "default";
            if (arguments.length > 1 && (arguments[1] === String ? r3 = "string" : arguments[1] === Number && (r3 = "number")), n2 && (Symbol.toPrimitive ? t3 = c(e3, Symbol.toPrimitive) : i(e3) && (t3 = Symbol.prototype.valueOf)), void 0 !== t3) {
              var u = t3.call(e3, r3);
              if (l(u)) return u;
              throw new s("unable to convert exotic object to primitive");
            }
            return "default" === r3 && (a(e3) || i(e3)) && (r3 = "string"), function(e4, t4) {
              if (null == e4) throw new s("Cannot call method on " + e4);
              if ("string" != typeof t4 || "number" !== t4 && "string" !== t4) throw new s('hint must be "string" or "number"');
              var r4, n3, a2, i2 = "string" === t4 ? ["toString", "valueOf"] : ["valueOf", "toString"];
              for (a2 = 0; a2 < i2.length; ++a2) if (r4 = e4[i2[a2]], o(r4) && (n3 = r4.call(e4), l(n3))) return n3;
              throw new s("No default value");
            }(e3, "default" === r3 ? "number" : r3);
          };
        }, 5701(e2, t2, r2) {
          "use strict";
          r2(1067)();
        }, 5795(e2, t2, r2) {
          "use strict";
          var n2 = r2(6549);
          if (n2) try {
            n2([], "length");
          } catch (e3) {
            n2 = null;
          }
          e2.exports = n2;
        }, 5880(e2) {
          "use strict";
          e2.exports = Math.pow;
        }, 6188(e2) {
          "use strict";
          e2.exports = Math.max;
        }, 6537(e2) {
          "use strict";
          e2.exports = function(e3) {
            return !!e3 && ("function" == typeof e3 || "object" == typeof e3);
          };
        }, 6549(e2) {
          "use strict";
          e2.exports = Object.getOwnPropertyDescriptor;
        }, 6556(e2, t2, r2) {
          "use strict";
          var n2 = r2(453), o = r2(3126), a = o([n2("%String.prototype.indexOf%")]);
          e2.exports = function(e3, t3) {
            var r3 = n2(e3, !!t3);
            return "function" == typeof r3 && a(e3, ".prototype.") > -1 ? o([r3]) : r3;
          };
        }, 6743(e2, t2, r2) {
          "use strict";
          var n2 = r2(9353);
          e2.exports = Function.prototype.bind || n2;
        }, 7119(e2) {
          "use strict";
          e2.exports = "undefined" != typeof Reflect && Reflect && Reflect.apply;
        }, 7176(e2, t2, r2) {
          "use strict";
          var n2, o = r2(3126), a = r2(5795);
          try {
            n2 = [].__proto__ === Array.prototype;
          } catch (e3) {
            if (!e3 || "object" != typeof e3 || !("code" in e3) || "ERR_PROTO_ACCESS" !== e3.code) throw e3;
          }
          var i = !!n2 && a && a(Object.prototype, "__proto__"), s = Object, l = s.getPrototypeOf;
          e2.exports = i && "function" == typeof i.get ? o([i.get]) : "function" == typeof l && function(e3) {
            return l(null == e3 ? e3 : s(e3));
          };
        }, 8002(e2) {
          "use strict";
          e2.exports = Math.min;
        }, 8068(e2) {
          "use strict";
          e2.exports = SyntaxError;
        }, 8452(e2, t2, r2) {
          "use strict";
          var n2 = r2(1189), o = "function" == typeof Symbol && "symbol" == typeof Symbol("foo"), a = Object.prototype.toString, i = Array.prototype.concat, s = r2(41), l = r2(592)(), c = function(e3, t3, r3, n3) {
            if (t3 in e3) {
              if (true === n3) {
                if (e3[t3] === r3) return;
              } else if ("function" != typeof (o2 = n3) || "[object Function]" !== a.call(o2) || !n3()) return;
            }
            var o2;
            l ? s(e3, t3, r3, true) : s(e3, t3, r3);
          }, u = function(e3, t3) {
            var r3 = arguments.length > 2 ? arguments[2] : {}, a2 = n2(t3);
            o && (a2 = i.call(a2, Object.getOwnPropertySymbols(t3)));
            for (var s2 = 0; s2 < a2.length; s2 += 1) c(e3, a2[s2], t3[a2[s2]], r3[a2[s2]]);
          };
          u.supportsDescriptors = !!l, e2.exports = u;
        }, 8648(e2) {
          "use strict";
          e2.exports = "undefined" != typeof Reflect && Reflect.getPrototypeOf || null;
        }, 8859(e2, t2, r2) {
          var n2 = "function" == typeof Map && Map.prototype, o = Object.getOwnPropertyDescriptor && n2 ? Object.getOwnPropertyDescriptor(Map.prototype, "size") : null, a = n2 && o && "function" == typeof o.get ? o.get : null, i = n2 && Map.prototype.forEach, s = "function" == typeof Set && Set.prototype, l = Object.getOwnPropertyDescriptor && s ? Object.getOwnPropertyDescriptor(Set.prototype, "size") : null, c = s && l && "function" == typeof l.get ? l.get : null, u = s && Set.prototype.forEach, h = "function" == typeof WeakMap && WeakMap.prototype ? WeakMap.prototype.has : null, f = "function" == typeof WeakSet && WeakSet.prototype ? WeakSet.prototype.has : null, p = "function" == typeof WeakRef && WeakRef.prototype ? WeakRef.prototype.deref : null, d = Boolean.prototype.valueOf, g = Object.prototype.toString, m = Function.prototype.toString, b = String.prototype.match, y = String.prototype.slice, w = String.prototype.replace, v = String.prototype.toUpperCase, k = String.prototype.toLowerCase, _ = RegExp.prototype.test, M = Array.prototype.concat, S = Array.prototype.join, E = Array.prototype.slice, C = Math.floor, x = "function" == typeof BigInt ? BigInt.prototype.valueOf : null, O = Object.getOwnPropertySymbols, j = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? Symbol.prototype.toString : null, R = "function" == typeof Symbol && "object" == typeof Symbol.iterator, A = "function" == typeof Symbol && Symbol.toStringTag && (Symbol.toStringTag, 1) ? Symbol.toStringTag : null, T = Object.prototype.propertyIsEnumerable, B = ("function" == typeof Reflect ? Reflect.getPrototypeOf : Object.getPrototypeOf) || ([].__proto__ === Array.prototype ? function(e3) {
            return e3.__proto__;
          } : null);
          function P(e3, t3) {
            if (e3 === 1 / 0 || e3 === -1 / 0 || e3 != e3 || e3 && e3 > -1e3 && e3 < 1e3 || _.call(/e/, t3)) return t3;
            var r3 = /[0-9](?=(?:[0-9]{3})+(?![0-9]))/g;
            if ("number" == typeof e3) {
              var n3 = e3 < 0 ? -C(-e3) : C(e3);
              if (n3 !== e3) {
                var o2 = String(n3), a2 = y.call(t3, o2.length + 1);
                return w.call(o2, r3, "$&_") + "." + w.call(w.call(a2, /([0-9]{3})/g, "$&_"), /_$/, "");
              }
            }
            return w.call(t3, r3, "$&_");
          }
          var N = r2(2634), L = N.custom, D = G(L) ? L : null, F = { __proto__: null, double: '"', single: "'" }, I = { __proto__: null, double: /(["\\])/g, single: /(['\\])/g };
          function $(e3, t3, r3) {
            var n3 = r3.quoteStyle || t3, o2 = F[n3];
            return o2 + e3 + o2;
          }
          function z(e3) {
            return w.call(String(e3), /"/g, "&quot;");
          }
          function q(e3) {
            return !A || !("object" == typeof e3 && (A in e3 || void 0 !== e3[A]));
          }
          function H(e3) {
            return "[object Array]" === V(e3) && q(e3);
          }
          function W(e3) {
            return "[object RegExp]" === V(e3) && q(e3);
          }
          function G(e3) {
            if (R) return e3 && "object" == typeof e3 && e3 instanceof Symbol;
            if ("symbol" == typeof e3) return true;
            if (!e3 || "object" != typeof e3 || !j) return false;
            try {
              return j.call(e3), true;
            } catch (e4) {
            }
            return false;
          }
          e2.exports = function e3(t3, n3, o2, s2) {
            var l2 = n3 || {};
            if (U(l2, "quoteStyle") && !U(F, l2.quoteStyle)) throw new TypeError('option "quoteStyle" must be "single" or "double"');
            if (U(l2, "maxStringLength") && ("number" == typeof l2.maxStringLength ? l2.maxStringLength < 0 && l2.maxStringLength !== 1 / 0 : null !== l2.maxStringLength)) throw new TypeError('option "maxStringLength", if provided, must be a positive integer, Infinity, or `null`');
            var g2 = !U(l2, "customInspect") || l2.customInspect;
            if ("boolean" != typeof g2 && "symbol" !== g2) throw new TypeError("option \"customInspect\", if provided, must be `true`, `false`, or `'symbol'`");
            if (U(l2, "indent") && null !== l2.indent && "	" !== l2.indent && !(parseInt(l2.indent, 10) === l2.indent && l2.indent > 0)) throw new TypeError('option "indent" must be "\\t", an integer > 0, or `null`');
            if (U(l2, "numericSeparator") && "boolean" != typeof l2.numericSeparator) throw new TypeError('option "numericSeparator", if provided, must be `true` or `false`');
            var v2 = l2.numericSeparator;
            if (void 0 === t3) return "undefined";
            if (null === t3) return "null";
            if ("boolean" == typeof t3) return t3 ? "true" : "false";
            if ("string" == typeof t3) return X(t3, l2);
            if ("number" == typeof t3) {
              if (0 === t3) return 1 / 0 / t3 > 0 ? "0" : "-0";
              var _2 = String(t3);
              return v2 ? P(t3, _2) : _2;
            }
            if ("bigint" == typeof t3) {
              var C2 = String(t3) + "n";
              return v2 ? P(t3, C2) : C2;
            }
            var O2 = void 0 === l2.depth ? 5 : l2.depth;
            if (void 0 === o2 && (o2 = 0), o2 >= O2 && O2 > 0 && "object" == typeof t3) return H(t3) ? "[Array]" : "[Object]";
            var L2, I2 = function(e4, t4) {
              var r3;
              if ("	" === e4.indent) r3 = "	";
              else {
                if (!("number" == typeof e4.indent && e4.indent > 0)) return null;
                r3 = S.call(Array(e4.indent + 1), " ");
              }
              return { base: r3, prev: S.call(Array(t4 + 1), r3) };
            }(l2, o2);
            if (void 0 === s2) s2 = [];
            else if (J(s2, t3) >= 0) return "[Circular]";
            function Y2(t4, r3, n4) {
              if (r3 && (s2 = E.call(s2)).push(r3), n4) {
                var a2 = { depth: l2.depth };
                return U(l2, "quoteStyle") && (a2.quoteStyle = l2.quoteStyle), e3(t4, a2, o2 + 1, s2);
              }
              return e3(t4, l2, o2 + 1, s2);
            }
            if ("function" == typeof t3 && !W(t3)) {
              var K2 = function(e4) {
                if (e4.name) return e4.name;
                var t4 = b.call(m.call(e4), /^function\s*([\w$]+)/);
                return t4 ? t4[1] : null;
              }(t3), ne = re(t3, Y2);
              return "[Function" + (K2 ? ": " + K2 : " (anonymous)") + "]" + (ne.length > 0 ? " { " + S.call(ne, ", ") + " }" : "");
            }
            if (G(t3)) {
              var oe = R ? w.call(String(t3), /^(Symbol\(.*\))_[^)]*$/, "$1") : j.call(t3);
              return "object" != typeof t3 || R ? oe : Z(oe);
            }
            if ((L2 = t3) && "object" == typeof L2 && ("undefined" != typeof HTMLElement && L2 instanceof HTMLElement || "string" == typeof L2.nodeName && "function" == typeof L2.getAttribute)) {
              for (var ae = "<" + k.call(String(t3.nodeName)), ie = t3.attributes || [], se = 0; se < ie.length; se++) ae += " " + ie[se].name + "=" + $(z(ie[se].value), "double", l2);
              return ae += ">", t3.childNodes && t3.childNodes.length && (ae += "..."), ae + "</" + k.call(String(t3.nodeName)) + ">";
            }
            if (H(t3)) {
              if (0 === t3.length) return "[]";
              var le = re(t3, Y2);
              return I2 && !function(e4) {
                for (var t4 = 0; t4 < e4.length; t4++) if (J(e4[t4], "\n") >= 0) return false;
                return true;
              }(le) ? "[" + te(le, I2) + "]" : "[ " + S.call(le, ", ") + " ]";
            }
            if (function(e4) {
              return "[object Error]" === V(e4) && q(e4);
            }(t3)) {
              var ce = re(t3, Y2);
              return "cause" in Error.prototype || !("cause" in t3) || T.call(t3, "cause") ? 0 === ce.length ? "[" + String(t3) + "]" : "{ [" + String(t3) + "] " + S.call(ce, ", ") + " }" : "{ [" + String(t3) + "] " + S.call(M.call("[cause]: " + Y2(t3.cause), ce), ", ") + " }";
            }
            if ("object" == typeof t3 && g2) {
              if (D && "function" == typeof t3[D] && N) return N(t3, { depth: O2 - o2 });
              if ("symbol" !== g2 && "function" == typeof t3.inspect) return t3.inspect();
            }
            if (function(e4) {
              if (!a || !e4 || "object" != typeof e4) return false;
              try {
                a.call(e4);
                try {
                  c.call(e4);
                } catch (e5) {
                  return true;
                }
                return e4 instanceof Map;
              } catch (e5) {
              }
              return false;
            }(t3)) {
              var ue = [];
              return i && i.call(t3, function(e4, r3) {
                ue.push(Y2(r3, t3, true) + " => " + Y2(e4, t3));
              }), ee("Map", a.call(t3), ue, I2);
            }
            if (function(e4) {
              if (!c || !e4 || "object" != typeof e4) return false;
              try {
                c.call(e4);
                try {
                  a.call(e4);
                } catch (e5) {
                  return true;
                }
                return e4 instanceof Set;
              } catch (e5) {
              }
              return false;
            }(t3)) {
              var he = [];
              return u && u.call(t3, function(e4) {
                he.push(Y2(e4, t3));
              }), ee("Set", c.call(t3), he, I2);
            }
            if (function(e4) {
              if (!h || !e4 || "object" != typeof e4) return false;
              try {
                h.call(e4, h);
                try {
                  f.call(e4, f);
                } catch (e5) {
                  return true;
                }
                return e4 instanceof WeakMap;
              } catch (e5) {
              }
              return false;
            }(t3)) return Q("WeakMap");
            if (function(e4) {
              if (!f || !e4 || "object" != typeof e4) return false;
              try {
                f.call(e4, f);
                try {
                  h.call(e4, h);
                } catch (e5) {
                  return true;
                }
                return e4 instanceof WeakSet;
              } catch (e5) {
              }
              return false;
            }(t3)) return Q("WeakSet");
            if (function(e4) {
              if (!p || !e4 || "object" != typeof e4) return false;
              try {
                return p.call(e4), true;
              } catch (e5) {
              }
              return false;
            }(t3)) return Q("WeakRef");
            if (function(e4) {
              return "[object Number]" === V(e4) && q(e4);
            }(t3)) return Z(Y2(Number(t3)));
            if (function(e4) {
              if (!e4 || "object" != typeof e4 || !x) return false;
              try {
                return x.call(e4), true;
              } catch (e5) {
              }
              return false;
            }(t3)) return Z(Y2(x.call(t3)));
            if (function(e4) {
              return "[object Boolean]" === V(e4) && q(e4);
            }(t3)) return Z(d.call(t3));
            if (function(e4) {
              return "[object String]" === V(e4) && q(e4);
            }(t3)) return Z(Y2(String(t3)));
            if ("undefined" != typeof window && t3 === window) return "{ [object Window] }";
            if ("undefined" != typeof globalThis && t3 === globalThis || void 0 !== r2.g && t3 === r2.g) return "{ [object globalThis] }";
            if (!function(e4) {
              return "[object Date]" === V(e4) && q(e4);
            }(t3) && !W(t3)) {
              var fe = re(t3, Y2), pe = B ? B(t3) === Object.prototype : t3 instanceof Object || t3.constructor === Object, de = t3 instanceof Object ? "" : "null prototype", ge = !pe && A && Object(t3) === t3 && A in t3 ? y.call(V(t3), 8, -1) : de ? "Object" : "", me = (pe || "function" != typeof t3.constructor ? "" : t3.constructor.name ? t3.constructor.name + " " : "") + (ge || de ? "[" + S.call(M.call([], ge || [], de || []), ": ") + "] " : "");
              return 0 === fe.length ? me + "{}" : I2 ? me + "{" + te(fe, I2) + "}" : me + "{ " + S.call(fe, ", ") + " }";
            }
            return String(t3);
          };
          var Y = Object.prototype.hasOwnProperty || function(e3) {
            return e3 in this;
          };
          function U(e3, t3) {
            return Y.call(e3, t3);
          }
          function V(e3) {
            return g.call(e3);
          }
          function J(e3, t3) {
            if (e3.indexOf) return e3.indexOf(t3);
            for (var r3 = 0, n3 = e3.length; r3 < n3; r3++) if (e3[r3] === t3) return r3;
            return -1;
          }
          function X(e3, t3) {
            if (e3.length > t3.maxStringLength) {
              var r3 = e3.length - t3.maxStringLength, n3 = "... " + r3 + " more character" + (r3 > 1 ? "s" : "");
              return X(y.call(e3, 0, t3.maxStringLength), t3) + n3;
            }
            var o2 = I[t3.quoteStyle || "single"];
            return o2.lastIndex = 0, $(w.call(w.call(e3, o2, "\\$1"), /[\x00-\x1f]/g, K), "single", t3);
          }
          function K(e3) {
            var t3 = e3.charCodeAt(0), r3 = { 8: "b", 9: "t", 10: "n", 12: "f", 13: "r" }[t3];
            return r3 ? "\\" + r3 : "\\x" + (t3 < 16 ? "0" : "") + v.call(t3.toString(16));
          }
          function Z(e3) {
            return "Object(" + e3 + ")";
          }
          function Q(e3) {
            return e3 + " { ? }";
          }
          function ee(e3, t3, r3, n3) {
            return e3 + " (" + t3 + ") {" + (n3 ? te(r3, n3) : S.call(r3, ", ")) + "}";
          }
          function te(e3, t3) {
            if (0 === e3.length) return "";
            var r3 = "\n" + t3.prev + t3.base;
            return r3 + S.call(e3, "," + r3) + "\n" + t3.prev;
          }
          function re(e3, t3) {
            var r3 = H(e3), n3 = [];
            if (r3) {
              n3.length = e3.length;
              for (var o2 = 0; o2 < e3.length; o2++) n3[o2] = U(e3, o2) ? t3(e3[o2], e3) : "";
            }
            var a2, i2 = "function" == typeof O ? O(e3) : [];
            if (R) {
              a2 = {};
              for (var s2 = 0; s2 < i2.length; s2++) a2["$" + i2[s2]] = i2[s2];
            }
            for (var l2 in e3) U(e3, l2) && (r3 && String(Number(l2)) === l2 && l2 < e3.length || R && a2["$" + l2] instanceof Symbol || (_.call(/[^\w$]/, l2) ? n3.push(t3(l2, e3) + ": " + t3(e3[l2], e3)) : n3.push(l2 + ": " + t3(e3[l2], e3))));
            if ("function" == typeof O) for (var c2 = 0; c2 < i2.length; c2++) T.call(e3, i2[c2]) && n3.push("[" + t3(i2[c2]) + "]: " + t3(e3[i2[c2]], e3));
            return n3;
          }
        }, 8875(e2, t2, r2) {
          "use strict";
          var n2;
          if (!Object.keys) {
            var o = Object.prototype.hasOwnProperty, a = Object.prototype.toString, i = r2(1093), s = Object.prototype.propertyIsEnumerable, l = !s.call({ toString: null }, "toString"), c = s.call(function() {
            }, "prototype"), u = ["toString", "toLocaleString", "valueOf", "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "constructor"], h = function(e3) {
              var t3 = e3.constructor;
              return t3 && t3.prototype === e3;
            }, f = { $applicationCache: true, $console: true, $external: true, $frame: true, $frameElement: true, $frames: true, $innerHeight: true, $innerWidth: true, $onmozfullscreenchange: true, $onmozfullscreenerror: true, $outerHeight: true, $outerWidth: true, $pageXOffset: true, $pageYOffset: true, $parent: true, $scrollLeft: true, $scrollTop: true, $scrollX: true, $scrollY: true, $self: true, $webkitIndexedDB: true, $webkitStorageInfo: true, $window: true }, p = function() {
              if ("undefined" == typeof window) return false;
              for (var e3 in window) try {
                if (!f["$" + e3] && o.call(window, e3) && null !== window[e3] && "object" == typeof window[e3]) try {
                  h(window[e3]);
                } catch (e4) {
                  return true;
                }
              } catch (e4) {
                return true;
              }
              return false;
            }();
            n2 = function(e3) {
              var t3 = null !== e3 && "object" == typeof e3, r3 = "[object Function]" === a.call(e3), n3 = i(e3), s2 = t3 && "[object String]" === a.call(e3), f2 = [];
              if (!t3 && !r3 && !n3) throw new TypeError("Object.keys called on a non-object");
              var d = c && r3;
              if (s2 && e3.length > 0 && !o.call(e3, 0)) for (var g = 0; g < e3.length; ++g) f2.push(String(g));
              if (n3 && e3.length > 0) for (var m = 0; m < e3.length; ++m) f2.push(String(m));
              else for (var b in e3) d && "prototype" === b || !o.call(e3, b) || f2.push(String(b));
              if (l) for (var y = function(e4) {
                if ("undefined" == typeof window || !p) return h(e4);
                try {
                  return h(e4);
                } catch (e5) {
                  return false;
                }
              }(e3), w = 0; w < u.length; ++w) y && "constructor" === u[w] || !o.call(e3, u[w]) || f2.push(u[w]);
              return f2;
            };
          }
          e2.exports = n2;
        }, 8968(e2) {
          "use strict";
          e2.exports = Math.floor;
        }, 9092(e2, t2, r2) {
          "use strict";
          var n2 = r2(1333);
          e2.exports = function() {
            return n2() && !!Symbol.toStringTag;
          };
        }, 9290(e2) {
          "use strict";
          e2.exports = RangeError;
        }, 9353(e2) {
          "use strict";
          var t2 = Object.prototype.toString, r2 = Math.max, n2 = function(e3, t3) {
            for (var r3 = [], n3 = 0; n3 < e3.length; n3 += 1) r3[n3] = e3[n3];
            for (var o = 0; o < t3.length; o += 1) r3[o + e3.length] = t3[o];
            return r3;
          };
          e2.exports = function(e3) {
            var o = this;
            if ("function" != typeof o || "[object Function]" !== t2.apply(o)) throw new TypeError("Function.prototype.bind called on incompatible " + o);
            for (var a, i = function(e4) {
              for (var t3 = [], r3 = 1, n3 = 0; r3 < e4.length; r3 += 1, n3 += 1) t3[n3] = e4[r3];
              return t3;
            }(arguments), s = r2(0, o.length - i.length), l = [], c = 0; c < s; c++) l[c] = "$" + c;
            if (a = Function("binder", "return function (" + function(e4) {
              for (var t3 = "", r3 = 0; r3 < e4.length; r3 += 1) t3 += e4[r3], r3 + 1 < e4.length && (t3 += ",");
              return t3;
            }(l) + "){ return binder.apply(this,arguments); }")(function() {
              if (this instanceof a) {
                var t3 = o.apply(this, n2(i, arguments));
                return Object(t3) === t3 ? t3 : this;
              }
              return o.apply(e3, n2(i, arguments));
            }), o.prototype) {
              var u = function() {
              };
              u.prototype = o.prototype, a.prototype = new u(), u.prototype = null;
            }
            return a;
          };
        }, 9383(e2) {
          "use strict";
          e2.exports = Error;
        }, 9487(e2) {
          "use strict";
          e2.exports = function(e3) {
            return "string" == typeof e3 || "symbol" == typeof e3;
          };
        }, 9538(e2) {
          "use strict";
          e2.exports = ReferenceError;
        }, 9600(e2) {
          "use strict";
          var t2, r2, n2 = Function.prototype.toString, o = "object" == typeof Reflect && null !== Reflect && Reflect.apply;
          if ("function" == typeof o && "function" == typeof Object.defineProperty) try {
            t2 = Object.defineProperty({}, "length", { get: function() {
              throw r2;
            } }), r2 = {}, o(function() {
              throw 42;
            }, null, t2);
          } catch (e3) {
            e3 !== r2 && (o = null);
          }
          else o = null;
          var a = /^\s*class\b/, i = function(e3) {
            try {
              var t3 = n2.call(e3);
              return a.test(t3);
            } catch (e4) {
              return false;
            }
          }, s = function(e3) {
            try {
              return !i(e3) && (n2.call(e3), true);
            } catch (e4) {
              return false;
            }
          }, l = Object.prototype.toString, c = "function" == typeof Symbol && !!Symbol.toStringTag, u = !(0 in [,]), h = function() {
            return false;
          };
          if ("object" == typeof document) {
            var f = document.all;
            l.call(f) === l.call(document.all) && (h = function(e3) {
              if ((u || !e3) && (void 0 === e3 || "object" == typeof e3)) try {
                var t3 = l.call(e3);
                return ("[object HTMLAllCollection]" === t3 || "[object HTML document.all class]" === t3 || "[object HTMLCollection]" === t3 || "[object Object]" === t3) && null == e3("");
              } catch (e4) {
              }
              return false;
            });
          }
          e2.exports = o ? function(e3) {
            if (h(e3)) return true;
            if (!e3) return false;
            if ("function" != typeof e3 && "object" != typeof e3) return false;
            try {
              o(e3, null, t2);
            } catch (e4) {
              if (e4 !== r2) return false;
            }
            return !i(e3) && s(e3);
          } : function(e3) {
            if (h(e3)) return true;
            if (!e3) return false;
            if ("function" != typeof e3 && "object" != typeof e3) return false;
            if (c) return s(e3);
            if (i(e3)) return false;
            var t3 = l.call(e3);
            return !("[object Function]" !== t3 && "[object GeneratorFunction]" !== t3 && !/^\[object HTML/.test(t3)) && s(e3);
          };
        }, 9612(e2) {
          "use strict";
          e2.exports = Object;
        }, 9675(e2) {
          "use strict";
          e2.exports = TypeError;
        }, 9705(e2, t2, r2) {
          "use strict";
          var n2 = r2(9675), o = r2(8859), a = r2(9487);
          e2.exports = function(e3, t3) {
            if (!a(t3)) throw new n2("Assertion failed: P is not a Property Key, got " + o(t3));
            return e3[t3];
          };
        }, 9721(e2, t2, r2) {
          "use strict";
          var n2 = r2(6556), o = r2(4035), a = n2("RegExp.prototype.exec"), i = r2(9675);
          e2.exports = function(e3) {
            if (!o(e3)) throw new i("`regex` must be a RegExp");
            return function(t3) {
              return null !== a(e3, t3);
            };
          };
        }, 9957(e2, t2, r2) {
          "use strict";
          var n2 = Function.prototype.call, o = Object.prototype.hasOwnProperty, a = r2(6743);
          e2.exports = a.call(n2, o);
        } }, t = {};
        function r(n2) {
          var o = t[n2];
          if (void 0 !== o) return o.exports;
          var a = t[n2] = { exports: {} };
          return e[n2](a, a.exports, r), a.exports;
        }
        r.d = (e2, t2) => {
          for (var n2 in t2) r.o(t2, n2) && !r.o(e2, n2) && Object.defineProperty(e2, n2, { enumerable: true, get: t2[n2] });
        }, r.g = function() {
          if ("object" == typeof globalThis) return globalThis;
          try {
            return this || new Function("return this")();
          } catch (e2) {
            if ("object" == typeof window) return window;
          }
        }(), r.o = (e2, t2) => Object.prototype.hasOwnProperty.call(e2, t2), r.r = (e2) => {
          "undefined" != typeof Symbol && Symbol.toStringTag && Object.defineProperty(e2, Symbol.toStringTag, { value: "Module" }), Object.defineProperty(e2, "__esModule", { value: true });
        };
        var n = {};
        return (() => {
          "use strict";
          var _a2, _b, _c, _d;
          r.r(n), r.d(n, { convertBg: () => Ei, extend: () => Ri, getContrast: () => xi, getDmBgColor: () => Oi, getDmFontColor: () => ji, htmlClass: () => l, init: () => Si, reset: () => Ai, run: () => Mi, updateStyle: () => Ci, validate: () => Ti });
          var e2 = {};
          r.r(e2), r.d(e2, { color: () => Ze, colorBurn: () => Ge, colorDodge: () => We, darken: () => qe, difference: () => Ve, exclusion: () => Je, hardLight: () => Ye, hue: () => Xe, lighten: () => He, luminosity: () => Qe, multiply: () => Ie, normal: () => Fe, overlay: () => ze, saturation: () => Ke, screen: () => $e, softLight: () => Ue }), r(5701);
          const t2 = `${(/* @__PURE__ */ new Date()).getTime()}${Math.floor(1e4 * Math.random())}`, o = "(prefers-color-scheme: dark)", a = "js_darkmode__", i = new RegExp(`${a}\\d+`), s = `js_darkmode_style__${t2}`, l = "data_color_scheme_dark", c = `data-darkmode-color-${t2}`, u = `data-darkmode-bgcolor-${t2}`, h = `data-darkmode-original-color-${t2}`, f = `data-darkmode-original-bgcolor-${t2}`, p = `data-darkmode-bgimage-${t2}`, d = `data-darkmode-bggradient-mix-color-${t2}`, g = `data-darkmode-complementary-bgimagecolor-${t2}`, m = ((_a2 = window.getInnerHeight) == null ? void 0 : _a2.call(window)) || window.innerHeight || document.documentElement.clientHeight, b = { BG_COLOR: ["background-color", "background-image", "background"], TEXT_SHADOW: ["text-shadow"], TEXT_COLOR: ["-webkit-text-stroke", "-webkit-text-stroke-color", "text-decoration", "text-decoration-color", "text-emphasis-color", "color", "-webkit-text-fill-color"], BORDER_COLOR: ["border-image", "-webkit-border-image", "border", "border-top", "border-right", "border-bottom", "border-left", "border-color", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color", "border-block-color", "border-block-start-color", "border-block-end-color", "border-inline-color", "border-inline-start-color", "border-inline-end-color", "outline", "outline-color", "box-shadow", "column-rule", "column-rule-color"] }, y = Object.keys(b).map((e3) => b[e3].join("|")).join("|").split("|"), w = ["TABLE", "TR", "TD", "TH"], v = / !important$/, k = /<\$#_SEMICOLON_#\$>/g, _ = "\\b((rgba?)|((ok)?lch)|((ok)?lab)|(color))\\([^)]+\\)", M = new RegExp(_, "i"), S = new RegExp(_, "ig"), E = /url\([^)]*\)/i;
          let C = function(e3) {
            return e3.FIRST_PAGE_STYLE = "firstPageStyle", e3.OTHER_PAGE_STYLE = "otherPageStyle", e3.FIRST_PAGE_STYLE_NO_MQ = "firstPageStyleNoMQ", e3.OTHER_PAGE_STYLE_NO_MQ = "otherPageStyleNoMQ", e3;
          }({}), x = function(e3) {
            return e3.LOW_CONTRAST = "low-contrast", e3.TEXT_BG_GRADIENT = "text-bg-gradient", e3;
          }({});
          const O = { aliceblue: [240, 248, 255], antiquewhite: [250, 235, 215], aqua: [0, 255, 255], aquamarine: [127, 255, 212], azure: [240, 255, 255], beige: [245, 245, 220], bisque: [255, 228, 196], black: [0, 0, 0], blanchedalmond: [255, 235, 205], blue: [0, 0, 255], blueviolet: [138, 43, 226], brown: [165, 42, 42], burlywood: [222, 184, 135], cadetblue: [95, 158, 160], chartreuse: [127, 255, 0], chocolate: [210, 105, 30], coral: [255, 127, 80], cornflowerblue: [100, 149, 237], cornsilk: [255, 248, 220], crimson: [220, 20, 60], cyan: [0, 255, 255], darkblue: [0, 0, 139], darkcyan: [0, 139, 139], darkgoldenrod: [184, 134, 11], darkgray: [169, 169, 169], darkgreen: [0, 100, 0], darkgrey: [169, 169, 169], darkkhaki: [189, 183, 107], darkmagenta: [139, 0, 139], darkolivegreen: [85, 107, 47], darkorange: [255, 140, 0], darkorchid: [153, 50, 204], darkred: [139, 0, 0], darksalmon: [233, 150, 122], darkseagreen: [143, 188, 143], darkslateblue: [72, 61, 139], darkslategray: [47, 79, 79], darkslategrey: [47, 79, 79], darkturquoise: [0, 206, 209], darkviolet: [148, 0, 211], deeppink: [255, 20, 147], deepskyblue: [0, 191, 255], dimgray: [105, 105, 105], dimgrey: [105, 105, 105], dodgerblue: [30, 144, 255], firebrick: [178, 34, 34], floralwhite: [255, 250, 240], forestgreen: [34, 139, 34], fuchsia: [255, 0, 255], gainsboro: [220, 220, 220], ghostwhite: [248, 248, 255], gold: [255, 215, 0], goldenrod: [218, 165, 32], gray: [128, 128, 128], green: [0, 128, 0], greenyellow: [173, 255, 47], grey: [128, 128, 128], honeydew: [240, 255, 240], hotpink: [255, 105, 180], indianred: [205, 92, 92], indigo: [75, 0, 130], ivory: [255, 255, 240], khaki: [240, 230, 140], lavender: [230, 230, 250], lavenderblush: [255, 240, 245], lawngreen: [124, 252, 0], lemonchiffon: [255, 250, 205], lightblue: [173, 216, 230], lightcoral: [240, 128, 128], lightcyan: [224, 255, 255], lightgoldenrodyellow: [250, 250, 210], lightgray: [211, 211, 211], lightgreen: [144, 238, 144], lightgrey: [211, 211, 211], lightpink: [255, 182, 193], lightsalmon: [255, 160, 122], lightseagreen: [32, 178, 170], lightskyblue: [135, 206, 250], lightslategray: [119, 136, 153], lightslategrey: [119, 136, 153], lightsteelblue: [176, 196, 222], lightyellow: [255, 255, 224], lime: [0, 255, 0], limegreen: [50, 205, 50], linen: [250, 240, 230], magenta: [255, 0, 255], maroon: [128, 0, 0], mediumaquamarine: [102, 205, 170], mediumblue: [0, 0, 205], mediumorchid: [186, 85, 211], mediumpurple: [147, 112, 219], mediumseagreen: [60, 179, 113], mediumslateblue: [123, 104, 238], mediumspringgreen: [0, 250, 154], mediumturquoise: [72, 209, 204], mediumvioletred: [199, 21, 133], midnightblue: [25, 25, 112], mintcream: [245, 255, 250], mistyrose: [255, 228, 225], moccasin: [255, 228, 181], navajowhite: [255, 222, 173], navy: [0, 0, 128], oldlace: [253, 245, 230], olive: [128, 128, 0], olivedrab: [107, 142, 35], orange: [255, 165, 0], orangered: [255, 69, 0], orchid: [218, 112, 214], palegoldenrod: [238, 232, 170], palegreen: [152, 251, 152], paleturquoise: [175, 238, 238], palevioletred: [219, 112, 147], papayawhip: [255, 239, 213], peachpuff: [255, 218, 185], peru: [205, 133, 63], pink: [255, 192, 203], plum: [221, 160, 221], powderblue: [176, 224, 230], purple: [128, 0, 128], rebeccapurple: [102, 51, 153], red: [255, 0, 0], rosybrown: [188, 143, 143], royalblue: [65, 105, 225], saddlebrown: [139, 69, 19], salmon: [250, 128, 114], sandybrown: [244, 164, 96], seagreen: [46, 139, 87], seashell: [255, 245, 238], sienna: [160, 82, 45], silver: [192, 192, 192], skyblue: [135, 206, 235], slateblue: [106, 90, 205], slategray: [112, 128, 144], slategrey: [112, 128, 144], snow: [255, 250, 250], springgreen: [0, 255, 127], steelblue: [70, 130, 180], tan: [210, 180, 140], teal: [0, 128, 128], thistle: [216, 191, 216], tomato: [255, 99, 71], turquoise: [64, 224, 208], violet: [238, 130, 238], wheat: [245, 222, 179], white: [255, 255, 255], whitesmoke: [245, 245, 245], yellow: [255, 255, 0], yellowgreen: [154, 205, 50] };
          for (const e3 in O) Object.freeze(O[e3]);
          const j = Object.freeze(O), R = /* @__PURE__ */ Object.create(null);
          for (const e3 in j) Object.hasOwn(j, e3) && (R[j[e3]] = e3);
          const A = { to: {}, get: {} };
          function T(e3, t3, r2) {
            return Math.min(Math.max(t3, e3), r2);
          }
          function B(e3) {
            const t3 = Math.round(e3).toString(16).toUpperCase();
            return t3.length < 2 ? "0" + t3 : t3;
          }
          A.get = function(e3) {
            let t3, r2;
            switch (e3.slice(0, 3).toLowerCase()) {
              case "hsl":
                t3 = A.get.hsl(e3), r2 = "hsl";
                break;
              case "hwb":
                t3 = A.get.hwb(e3), r2 = "hwb";
                break;
              default:
                t3 = A.get.rgb(e3), r2 = "rgb";
            }
            return t3 ? { model: r2, value: t3 } : null;
          }, A.get.rgb = function(e3) {
            if (!e3) return null;
            let t3, r2, n2, o2 = [0, 0, 0, 1];
            if (t3 = e3.match(/^#([a-f\d]{6})([a-f\d]{2})?$/i)) {
              for (n2 = t3[2], t3 = t3[1], r2 = 0; r2 < 3; r2++) {
                const e4 = 2 * r2;
                o2[r2] = Number.parseInt(t3.slice(e4, e4 + 2), 16);
              }
              n2 && (o2[3] = Number.parseInt(n2, 16) / 255);
            } else if (t3 = e3.match(/^#([a-f\d]{3,4})$/i)) {
              for (t3 = t3[1], n2 = t3[3], r2 = 0; r2 < 3; r2++) o2[r2] = Number.parseInt(t3[r2] + t3[r2], 16);
              n2 && (o2[3] = Number.parseInt(n2 + n2, 16) / 255);
            } else if (t3 = e3.match(/^rgba?\(\s*([+-]?(?:\d*\.)?\d+(?:e\d+)?)(?=[\s,])\s*(?:,\s*)?([+-]?(?:\d*\.)?\d+(?:e\d+)?)(?=[\s,])\s*(?:,\s*)?([+-]?(?:\d*\.)?\d+(?:e\d+)?)\s*(?:[\s,|/]\s*([+-]?(?:\d*\.)?\d+(?:e\d+)?)(%?)\s*)?\)$/i)) {
              for (r2 = 0; r2 < 3; r2++) o2[r2] = Number.parseFloat(t3[r2 + 1]);
              t3[4] && (o2[3] = t3[5] ? 0.01 * Number.parseFloat(t3[4]) : Number.parseFloat(t3[4]));
            } else {
              if (!(t3 = e3.match(/^rgba?\(\s*([+-]?[\d.]+)%\s*,?\s*([+-]?[\d.]+)%\s*,?\s*([+-]?[\d.]+)%\s*(?:[\s,|/]\s*([+-]?[\d.]+)(%?)\s*)?\)$/i))) return (t3 = e3.toLowerCase().match(/^(\w+)$/)) ? "transparent" === t3[1] ? [0, 0, 0, 0] : Object.hasOwn(j, t3[1]) ? (o2 = j[t3[1]].slice(), o2[3] = 1, o2) : null : null;
              for (r2 = 0; r2 < 3; r2++) o2[r2] = Math.round(2.55 * Number.parseFloat(t3[r2 + 1]));
              t3[4] && (o2[3] = t3[5] ? 0.01 * Number.parseFloat(t3[4]) : Number.parseFloat(t3[4]));
            }
            for (r2 = 0; r2 < 3; r2++) o2[r2] = T(o2[r2], 0, 255);
            return o2[3] = T(o2[3], 0, 1), o2;
          }, A.get.hsl = function(e3) {
            if (!e3) return null;
            const t3 = e3.match(/^hsla?\(\s*([+-]?(?:\d{0,3}\.)?\d+)(?:deg)?\s*,?\s*([+-]?[\d.]+)%\s*,?\s*([+-]?[\d.]+)%\s*(?:[,|/]\s*([+-]?(?=\.\d|\d)(?:0|[1-9]\d*)?(?:\.\d*)?(?:e[+-]?\d+)?)\s*)?\)$/i);
            if (t3) {
              const e4 = Number.parseFloat(t3[4]);
              return [(Number.parseFloat(t3[1]) % 360 + 360) % 360, T(Number.parseFloat(t3[2]), 0, 100), T(Number.parseFloat(t3[3]), 0, 100), T(Number.isNaN(e4) ? 1 : e4, 0, 1)];
            }
            return null;
          }, A.get.hwb = function(e3) {
            if (!e3) return null;
            const t3 = e3.match(/^hwb\(\s*([+-]?\d{0,3}(?:\.\d+)?)(?:deg)?\s*[\s,]\s*([+-]?[\d.]+)%\s*[\s,]\s*([+-]?[\d.]+)%\s*(?:[\s,]\s*([+-]?(?=\.\d|\d)(?:0|[1-9]\d*)?(?:\.\d*)?(?:e[+-]?\d+)?)\s*)?\)$/i);
            if (t3) {
              const e4 = Number.parseFloat(t3[4]);
              return [(Number.parseFloat(t3[1]) % 360 + 360) % 360, T(Number.parseFloat(t3[2]), 0, 100), T(Number.parseFloat(t3[3]), 0, 100), T(Number.isNaN(e4) ? 1 : e4, 0, 1)];
            }
            return null;
          }, A.to.hex = function(...e3) {
            return "#" + B(e3[0]) + B(e3[1]) + B(e3[2]) + (e3[3] < 1 ? B(Math.round(255 * e3[3])) : "");
          }, A.to.rgb = function(...e3) {
            return e3.length < 4 || 1 === e3[3] ? "rgb(" + Math.round(e3[0]) + ", " + Math.round(e3[1]) + ", " + Math.round(e3[2]) + ")" : "rgba(" + Math.round(e3[0]) + ", " + Math.round(e3[1]) + ", " + Math.round(e3[2]) + ", " + e3[3] + ")";
          }, A.to.rgb.percent = function(...e3) {
            const t3 = Math.round(e3[0] / 255 * 100), r2 = Math.round(e3[1] / 255 * 100), n2 = Math.round(e3[2] / 255 * 100);
            return e3.length < 4 || 1 === e3[3] ? "rgb(" + t3 + "%, " + r2 + "%, " + n2 + "%)" : "rgba(" + t3 + "%, " + r2 + "%, " + n2 + "%, " + e3[3] + ")";
          }, A.to.hsl = function(...e3) {
            return e3.length < 4 || 1 === e3[3] ? "hsl(" + e3[0] + ", " + e3[1] + "%, " + e3[2] + "%)" : "hsla(" + e3[0] + ", " + e3[1] + "%, " + e3[2] + "%, " + e3[3] + ")";
          }, A.to.hwb = function(...e3) {
            let t3 = "";
            return e3.length >= 4 && 1 !== e3[3] && (t3 = ", " + e3[3]), "hwb(" + e3[0] + ", " + e3[1] + "%, " + e3[2] + "%" + t3 + ")";
          }, A.to.keyword = function(...e3) {
            return R[e3.slice(0, 3)];
          };
          const P = A, N = { aliceblue: [240, 248, 255], antiquewhite: [250, 235, 215], aqua: [0, 255, 255], aquamarine: [127, 255, 212], azure: [240, 255, 255], beige: [245, 245, 220], bisque: [255, 228, 196], black: [0, 0, 0], blanchedalmond: [255, 235, 205], blue: [0, 0, 255], blueviolet: [138, 43, 226], brown: [165, 42, 42], burlywood: [222, 184, 135], cadetblue: [95, 158, 160], chartreuse: [127, 255, 0], chocolate: [210, 105, 30], coral: [255, 127, 80], cornflowerblue: [100, 149, 237], cornsilk: [255, 248, 220], crimson: [220, 20, 60], cyan: [0, 255, 255], darkblue: [0, 0, 139], darkcyan: [0, 139, 139], darkgoldenrod: [184, 134, 11], darkgray: [169, 169, 169], darkgreen: [0, 100, 0], darkgrey: [169, 169, 169], darkkhaki: [189, 183, 107], darkmagenta: [139, 0, 139], darkolivegreen: [85, 107, 47], darkorange: [255, 140, 0], darkorchid: [153, 50, 204], darkred: [139, 0, 0], darksalmon: [233, 150, 122], darkseagreen: [143, 188, 143], darkslateblue: [72, 61, 139], darkslategray: [47, 79, 79], darkslategrey: [47, 79, 79], darkturquoise: [0, 206, 209], darkviolet: [148, 0, 211], deeppink: [255, 20, 147], deepskyblue: [0, 191, 255], dimgray: [105, 105, 105], dimgrey: [105, 105, 105], dodgerblue: [30, 144, 255], firebrick: [178, 34, 34], floralwhite: [255, 250, 240], forestgreen: [34, 139, 34], fuchsia: [255, 0, 255], gainsboro: [220, 220, 220], ghostwhite: [248, 248, 255], gold: [255, 215, 0], goldenrod: [218, 165, 32], gray: [128, 128, 128], green: [0, 128, 0], greenyellow: [173, 255, 47], grey: [128, 128, 128], honeydew: [240, 255, 240], hotpink: [255, 105, 180], indianred: [205, 92, 92], indigo: [75, 0, 130], ivory: [255, 255, 240], khaki: [240, 230, 140], lavender: [230, 230, 250], lavenderblush: [255, 240, 245], lawngreen: [124, 252, 0], lemonchiffon: [255, 250, 205], lightblue: [173, 216, 230], lightcoral: [240, 128, 128], lightcyan: [224, 255, 255], lightgoldenrodyellow: [250, 250, 210], lightgray: [211, 211, 211], lightgreen: [144, 238, 144], lightgrey: [211, 211, 211], lightpink: [255, 182, 193], lightsalmon: [255, 160, 122], lightseagreen: [32, 178, 170], lightskyblue: [135, 206, 250], lightslategray: [119, 136, 153], lightslategrey: [119, 136, 153], lightsteelblue: [176, 196, 222], lightyellow: [255, 255, 224], lime: [0, 255, 0], limegreen: [50, 205, 50], linen: [250, 240, 230], magenta: [255, 0, 255], maroon: [128, 0, 0], mediumaquamarine: [102, 205, 170], mediumblue: [0, 0, 205], mediumorchid: [186, 85, 211], mediumpurple: [147, 112, 219], mediumseagreen: [60, 179, 113], mediumslateblue: [123, 104, 238], mediumspringgreen: [0, 250, 154], mediumturquoise: [72, 209, 204], mediumvioletred: [199, 21, 133], midnightblue: [25, 25, 112], mintcream: [245, 255, 250], mistyrose: [255, 228, 225], moccasin: [255, 228, 181], navajowhite: [255, 222, 173], navy: [0, 0, 128], oldlace: [253, 245, 230], olive: [128, 128, 0], olivedrab: [107, 142, 35], orange: [255, 165, 0], orangered: [255, 69, 0], orchid: [218, 112, 214], palegoldenrod: [238, 232, 170], palegreen: [152, 251, 152], paleturquoise: [175, 238, 238], palevioletred: [219, 112, 147], papayawhip: [255, 239, 213], peachpuff: [255, 218, 185], peru: [205, 133, 63], pink: [255, 192, 203], plum: [221, 160, 221], powderblue: [176, 224, 230], purple: [128, 0, 128], rebeccapurple: [102, 51, 153], red: [255, 0, 0], rosybrown: [188, 143, 143], royalblue: [65, 105, 225], saddlebrown: [139, 69, 19], salmon: [250, 128, 114], sandybrown: [244, 164, 96], seagreen: [46, 139, 87], seashell: [255, 245, 238], sienna: [160, 82, 45], silver: [192, 192, 192], skyblue: [135, 206, 235], slateblue: [106, 90, 205], slategray: [112, 128, 144], slategrey: [112, 128, 144], snow: [255, 250, 250], springgreen: [0, 255, 127], steelblue: [70, 130, 180], tan: [210, 180, 140], teal: [0, 128, 128], thistle: [216, 191, 216], tomato: [255, 99, 71], turquoise: [64, 224, 208], violet: [238, 130, 238], wheat: [245, 222, 179], white: [255, 255, 255], whitesmoke: [245, 245, 245], yellow: [255, 255, 0], yellowgreen: [154, 205, 50] };
          for (const e3 in N) Object.freeze(N[e3]);
          const L = Object.freeze(N), D = {};
          for (const e3 of Object.keys(L)) D[L[e3]] = e3;
          const F = { rgb: { channels: 3, labels: "rgb" }, hsl: { channels: 3, labels: "hsl" }, hsv: { channels: 3, labels: "hsv" }, hwb: { channels: 3, labels: "hwb" }, cmyk: { channels: 4, labels: "cmyk" }, xyz: { channels: 3, labels: "xyz" }, lab: { channels: 3, labels: "lab" }, oklab: { channels: 3, labels: ["okl", "oka", "okb"] }, lch: { channels: 3, labels: "lch" }, oklch: { channels: 3, labels: ["okl", "okc", "okh"] }, hex: { channels: 1, labels: ["hex"] }, keyword: { channels: 1, labels: ["keyword"] }, ansi16: { channels: 1, labels: ["ansi16"] }, ansi256: { channels: 1, labels: ["ansi256"] }, hcg: { channels: 3, labels: ["h", "c", "g"] }, apple: { channels: 3, labels: ["r16", "g16", "b16"] }, gray: { channels: 1, labels: ["gray"] } }, I = F, $ = (6 / 29) ** 3;
          function z(e3) {
            const t3 = e3 > 31308e-7 ? 1.055 * e3 ** (1 / 2.4) - 0.055 : 12.92 * e3;
            return Math.min(Math.max(0, t3), 1);
          }
          function q(e3) {
            return e3 > 0.04045 ? ((e3 + 0.055) / 1.055) ** 2.4 : e3 / 12.92;
          }
          for (const e3 of Object.keys(F)) {
            if (!("channels" in F[e3])) throw new Error("missing channels property: " + e3);
            if (!("labels" in F[e3])) throw new Error("missing channel labels property: " + e3);
            if (F[e3].labels.length !== F[e3].channels) throw new Error("channel and label counts mismatch: " + e3);
            const { channels: t3, labels: r2 } = F[e3];
            delete F[e3].channels, delete F[e3].labels, Object.defineProperty(F[e3], "channels", { value: t3 }), Object.defineProperty(F[e3], "labels", { value: r2 });
          }
          function H(e3, t3) {
            return (e3[0] - t3[0]) ** 2 + (e3[1] - t3[1]) ** 2 + (e3[2] - t3[2]) ** 2;
          }
          function W(e3, t3) {
            return function(r2) {
              return t3(e3(r2));
            };
          }
          function G(e3, t3) {
            const r2 = [t3[e3].parent, e3];
            let n2 = I[t3[e3].parent][e3], o2 = t3[e3].parent;
            for (; t3[o2].parent; ) r2.unshift(t3[o2].parent), n2 = W(I[t3[o2].parent][o2], n2), o2 = t3[o2].parent;
            return n2.conversion = r2, n2;
          }
          F.rgb.hsl = function(e3) {
            const t3 = e3[0] / 255, r2 = e3[1] / 255, n2 = e3[2] / 255, o2 = Math.min(t3, r2, n2), a2 = Math.max(t3, r2, n2), i2 = a2 - o2;
            let s2, l2;
            switch (a2) {
              case o2:
                s2 = 0;
                break;
              case t3:
                s2 = (r2 - n2) / i2;
                break;
              case r2:
                s2 = 2 + (n2 - t3) / i2;
                break;
              case n2:
                s2 = 4 + (t3 - r2) / i2;
            }
            s2 = Math.min(60 * s2, 360), s2 < 0 && (s2 += 360);
            const c2 = (o2 + a2) / 2;
            return l2 = a2 === o2 ? 0 : c2 <= 0.5 ? i2 / (a2 + o2) : i2 / (2 - a2 - o2), [s2, 100 * l2, 100 * c2];
          }, F.rgb.hsv = function(e3) {
            let t3, r2, n2, o2, a2;
            const i2 = e3[0] / 255, s2 = e3[1] / 255, l2 = e3[2] / 255, c2 = Math.max(i2, s2, l2), u2 = c2 - Math.min(i2, s2, l2), h2 = function(e4) {
              return (c2 - e4) / 6 / u2 + 0.5;
            };
            if (0 === u2) o2 = 0, a2 = 0;
            else {
              switch (a2 = u2 / c2, t3 = h2(i2), r2 = h2(s2), n2 = h2(l2), c2) {
                case i2:
                  o2 = n2 - r2;
                  break;
                case s2:
                  o2 = 1 / 3 + t3 - n2;
                  break;
                case l2:
                  o2 = 2 / 3 + r2 - t3;
              }
              o2 < 0 ? o2 += 1 : o2 > 1 && (o2 -= 1);
            }
            return [360 * o2, 100 * a2, 100 * c2];
          }, F.rgb.hwb = function(e3) {
            const t3 = e3[0], r2 = e3[1];
            let n2 = e3[2];
            const o2 = F.rgb.hsl(e3)[0], a2 = 1 / 255 * Math.min(t3, Math.min(r2, n2));
            return n2 = 1 - 1 / 255 * Math.max(t3, Math.max(r2, n2)), [o2, 100 * a2, 100 * n2];
          }, F.rgb.oklab = function(e3) {
            const t3 = q(e3[0] / 255), r2 = q(e3[1] / 255), n2 = q(e3[2] / 255), o2 = Math.cbrt(0.4122214708 * t3 + 0.5363325363 * r2 + 0.0514459929 * n2), a2 = Math.cbrt(0.2119034982 * t3 + 0.6806995451 * r2 + 0.1073969566 * n2), i2 = Math.cbrt(0.0883024619 * t3 + 0.2817188376 * r2 + 0.6299787005 * n2);
            return [100 * (0.2104542553 * o2 + 0.793617785 * a2 - 0.0040720468 * i2), 100 * (1.9779984951 * o2 - 2.428592205 * a2 + 0.4505937099 * i2), 100 * (0.0259040371 * o2 + 0.7827717662 * a2 - 0.808675766 * i2)];
          }, F.rgb.cmyk = function(e3) {
            const t3 = e3[0] / 255, r2 = e3[1] / 255, n2 = e3[2] / 255, o2 = Math.min(1 - t3, 1 - r2, 1 - n2);
            return [100 * ((1 - t3 - o2) / (1 - o2) || 0), 100 * ((1 - r2 - o2) / (1 - o2) || 0), 100 * ((1 - n2 - o2) / (1 - o2) || 0), 100 * o2];
          }, F.rgb.keyword = function(e3) {
            const t3 = D[e3];
            if (t3) return t3;
            let r2, n2 = Number.POSITIVE_INFINITY;
            for (const t4 of Object.keys(L)) {
              const o2 = H(e3, L[t4]);
              o2 < n2 && (n2 = o2, r2 = t4);
            }
            return r2;
          }, F.keyword.rgb = function(e3) {
            return [...L[e3]];
          }, F.rgb.xyz = function(e3) {
            const t3 = q(e3[0] / 255), r2 = q(e3[1] / 255), n2 = q(e3[2] / 255);
            return [100 * (0.4124564 * t3 + 0.3575761 * r2 + 0.1804375 * n2), 100 * (0.2126729 * t3 + 0.7151522 * r2 + 0.072175 * n2), 100 * (0.0193339 * t3 + 0.119192 * r2 + 0.9503041 * n2)];
          }, F.rgb.lab = function(e3) {
            const t3 = F.rgb.xyz(e3);
            let r2 = t3[0], n2 = t3[1], o2 = t3[2];
            return r2 /= 95.047, n2 /= 100, o2 /= 108.883, r2 = r2 > $ ? r2 ** (1 / 3) : 7.787 * r2 + 16 / 116, n2 = n2 > $ ? n2 ** (1 / 3) : 7.787 * n2 + 16 / 116, o2 = o2 > $ ? o2 ** (1 / 3) : 7.787 * o2 + 16 / 116, [116 * n2 - 16, 500 * (r2 - n2), 200 * (n2 - o2)];
          }, F.hsl.rgb = function(e3) {
            const t3 = e3[0] / 360, r2 = e3[1] / 100, n2 = e3[2] / 100;
            let o2, a2;
            if (0 === r2) return a2 = 255 * n2, [a2, a2, a2];
            const i2 = n2 < 0.5 ? n2 * (1 + r2) : n2 + r2 - n2 * r2, s2 = 2 * n2 - i2, l2 = [0, 0, 0];
            for (let e4 = 0; e4 < 3; e4++) o2 = t3 + 1 / 3 * -(e4 - 1), o2 < 0 && o2++, o2 > 1 && o2--, a2 = 6 * o2 < 1 ? s2 + 6 * (i2 - s2) * o2 : 2 * o2 < 1 ? i2 : 3 * o2 < 2 ? s2 + (i2 - s2) * (2 / 3 - o2) * 6 : s2, l2[e4] = 255 * a2;
            return l2;
          }, F.hsl.hsv = function(e3) {
            const t3 = e3[0];
            let r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = r2;
            const a2 = Math.max(n2, 0.01);
            return n2 *= 2, r2 *= n2 <= 1 ? n2 : 2 - n2, o2 *= a2 <= 1 ? a2 : 2 - a2, [t3, 100 * (0 === n2 ? 2 * o2 / (a2 + o2) : 2 * r2 / (n2 + r2)), (n2 + r2) / 2 * 100];
          }, F.hsv.rgb = function(e3) {
            const t3 = e3[0] / 60, r2 = e3[1] / 100;
            let n2 = e3[2] / 100;
            const o2 = Math.floor(t3) % 6, a2 = t3 - Math.floor(t3), i2 = 255 * n2 * (1 - r2), s2 = 255 * n2 * (1 - r2 * a2), l2 = 255 * n2 * (1 - r2 * (1 - a2));
            switch (n2 *= 255, o2) {
              case 0:
                return [n2, l2, i2];
              case 1:
                return [s2, n2, i2];
              case 2:
                return [i2, n2, l2];
              case 3:
                return [i2, s2, n2];
              case 4:
                return [l2, i2, n2];
              case 5:
                return [n2, i2, s2];
            }
          }, F.hsv.hsl = function(e3) {
            const t3 = e3[0], r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = Math.max(n2, 0.01);
            let a2, i2;
            i2 = (2 - r2) * n2;
            const s2 = (2 - r2) * o2;
            return a2 = r2 * o2, a2 /= s2 <= 1 ? s2 : 2 - s2, a2 = a2 || 0, i2 /= 2, [t3, 100 * a2, 100 * i2];
          }, F.hwb.rgb = function(e3) {
            const t3 = e3[0] / 360;
            let r2 = e3[1] / 100, n2 = e3[2] / 100;
            const o2 = r2 + n2;
            let a2;
            o2 > 1 && (r2 /= o2, n2 /= o2);
            const i2 = Math.floor(6 * t3), s2 = 1 - n2;
            a2 = 6 * t3 - i2, 1 & i2 && (a2 = 1 - a2);
            const l2 = r2 + a2 * (s2 - r2);
            let c2, u2, h2;
            switch (i2) {
              default:
              case 6:
              case 0:
                c2 = s2, u2 = l2, h2 = r2;
                break;
              case 1:
                c2 = l2, u2 = s2, h2 = r2;
                break;
              case 2:
                c2 = r2, u2 = s2, h2 = l2;
                break;
              case 3:
                c2 = r2, u2 = l2, h2 = s2;
                break;
              case 4:
                c2 = l2, u2 = r2, h2 = s2;
                break;
              case 5:
                c2 = s2, u2 = r2, h2 = l2;
            }
            return [255 * c2, 255 * u2, 255 * h2];
          }, F.cmyk.rgb = function(e3) {
            const t3 = e3[0] / 100, r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = e3[3] / 100;
            return [255 * (1 - Math.min(1, t3 * (1 - o2) + o2)), 255 * (1 - Math.min(1, r2 * (1 - o2) + o2)), 255 * (1 - Math.min(1, n2 * (1 - o2) + o2))];
          }, F.xyz.rgb = function(e3) {
            const t3 = e3[0] / 100, r2 = e3[1] / 100, n2 = e3[2] / 100;
            let o2, a2, i2;
            return o2 = 3.2404542 * t3 + -1.5371385 * r2 + -0.4985314 * n2, a2 = -0.969266 * t3 + 1.8760108 * r2 + 0.041556 * n2, i2 = 0.0556434 * t3 + -0.2040259 * r2 + 1.0572252 * n2, o2 = z(o2), a2 = z(a2), i2 = z(i2), [255 * o2, 255 * a2, 255 * i2];
          }, F.xyz.lab = function(e3) {
            let t3 = e3[0], r2 = e3[1], n2 = e3[2];
            return t3 /= 95.047, r2 /= 100, n2 /= 108.883, t3 = t3 > $ ? t3 ** (1 / 3) : 7.787 * t3 + 16 / 116, r2 = r2 > $ ? r2 ** (1 / 3) : 7.787 * r2 + 16 / 116, n2 = n2 > $ ? n2 ** (1 / 3) : 7.787 * n2 + 16 / 116, [116 * r2 - 16, 500 * (t3 - r2), 200 * (r2 - n2)];
          }, F.xyz.oklab = function(e3) {
            const t3 = e3[0] / 100, r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = Math.cbrt(0.8189330101 * t3 + 0.3618667424 * r2 - 0.1288597137 * n2), a2 = Math.cbrt(0.0329845436 * t3 + 0.9293118715 * r2 + 0.0361456387 * n2), i2 = Math.cbrt(0.0482003018 * t3 + 0.2643662691 * r2 + 0.633851707 * n2);
            return [100 * (0.2104542553 * o2 + 0.793617785 * a2 - 0.0040720468 * i2), 100 * (1.9779984951 * o2 - 2.428592205 * a2 + 0.4505937099 * i2), 100 * (0.0259040371 * o2 + 0.7827717662 * a2 - 0.808675766 * i2)];
          }, F.oklab.oklch = function(e3) {
            return F.lab.lch(e3);
          }, F.oklab.xyz = function(e3) {
            const t3 = e3[0] / 100, r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = (0.999999998 * t3 + 0.396337792 * r2 + 0.215803758 * n2) ** 3, a2 = (1.000000008 * t3 - 0.105561342 * r2 - 0.063854175 * n2) ** 3, i2 = (1.000000055 * t3 - 0.089484182 * r2 - 1.291485538 * n2) ** 3;
            return [100 * (1.227013851 * o2 - 0.55779998 * a2 + 0.281256149 * i2), 100 * (-0.040580178 * o2 + 1.11225687 * a2 - 0.071676679 * i2), 100 * (-0.076381285 * o2 - 0.421481978 * a2 + 1.58616322 * i2)];
          }, F.oklab.rgb = function(e3) {
            const t3 = e3[0] / 100, r2 = e3[1] / 100, n2 = e3[2] / 100, o2 = (t3 + 0.3963377774 * r2 + 0.2158037573 * n2) ** 3, a2 = (t3 - 0.1055613458 * r2 - 0.0638541728 * n2) ** 3, i2 = (t3 - 0.0894841775 * r2 - 1.291485548 * n2) ** 3;
            return [255 * z(4.0767416621 * o2 - 3.3077115913 * a2 + 0.2309699292 * i2), 255 * z(-1.2684380046 * o2 + 2.6097574011 * a2 - 0.3413193965 * i2), 255 * z(-0.0041960863 * o2 - 0.7034186147 * a2 + 1.707614701 * i2)];
          }, F.oklch.oklab = function(e3) {
            return F.lch.lab(e3);
          }, F.lab.xyz = function(e3) {
            let t3, r2, n2;
            r2 = (e3[0] + 16) / 116, t3 = e3[1] / 500 + r2, n2 = r2 - e3[2] / 200;
            const o2 = r2 ** 3, a2 = t3 ** 3, i2 = n2 ** 3;
            return r2 = o2 > $ ? o2 : (r2 - 16 / 116) / 7.787, t3 = a2 > $ ? a2 : (t3 - 16 / 116) / 7.787, n2 = i2 > $ ? i2 : (n2 - 16 / 116) / 7.787, t3 *= 95.047, r2 *= 100, n2 *= 108.883, [t3, r2, n2];
          }, F.lab.lch = function(e3) {
            const t3 = e3[0], r2 = e3[1], n2 = e3[2];
            let o2;
            return o2 = 360 * Math.atan2(n2, r2) / 2 / Math.PI, o2 < 0 && (o2 += 360), [t3, Math.sqrt(r2 * r2 + n2 * n2), o2];
          }, F.lch.lab = function(e3) {
            const t3 = e3[0], r2 = e3[1], n2 = e3[2] / 360 * 2 * Math.PI;
            return [t3, r2 * Math.cos(n2), r2 * Math.sin(n2)];
          }, F.rgb.ansi16 = function(e3, t3 = null) {
            const [r2, n2, o2] = e3;
            let a2 = null === t3 ? F.rgb.hsv(e3)[2] : t3;
            if (a2 = Math.round(a2 / 50), 0 === a2) return 30;
            let i2 = 30 + (Math.round(o2 / 255) << 2 | Math.round(n2 / 255) << 1 | Math.round(r2 / 255));
            return 2 === a2 && (i2 += 60), i2;
          }, F.hsv.ansi16 = function(e3) {
            return F.rgb.ansi16(F.hsv.rgb(e3), e3[2]);
          }, F.rgb.ansi256 = function(e3) {
            const t3 = e3[0], r2 = e3[1], n2 = e3[2];
            return t3 >> 4 == r2 >> 4 && r2 >> 4 == n2 >> 4 ? t3 < 8 ? 16 : t3 > 248 ? 231 : Math.round((t3 - 8) / 247 * 24) + 232 : 16 + 36 * Math.round(t3 / 255 * 5) + 6 * Math.round(r2 / 255 * 5) + Math.round(n2 / 255 * 5);
          }, F.ansi16.rgb = function(e3) {
            let t3 = (e3 = e3[0]) % 10;
            if (0 === t3 || 7 === t3) return e3 > 50 && (t3 += 3.5), t3 = t3 / 10.5 * 255, [t3, t3, t3];
            const r2 = 0.5 * (Math.trunc(e3 > 50) + 1);
            return [(1 & t3) * r2 * 255, (t3 >> 1 & 1) * r2 * 255, (t3 >> 2 & 1) * r2 * 255];
          }, F.ansi256.rgb = function(e3) {
            if ((e3 = e3[0]) >= 232) {
              const t4 = 10 * (e3 - 232) + 8;
              return [t4, t4, t4];
            }
            let t3;
            return e3 -= 16, [Math.floor(e3 / 36) / 5 * 255, Math.floor((t3 = e3 % 36) / 6) / 5 * 255, t3 % 6 / 5 * 255];
          }, F.rgb.hex = function(e3) {
            const t3 = (((255 & Math.round(e3[0])) << 16) + ((255 & Math.round(e3[1])) << 8) + (255 & Math.round(e3[2]))).toString(16).toUpperCase();
            return "000000".slice(t3.length) + t3;
          }, F.hex.rgb = function(e3) {
            const t3 = e3.toString(16).match(/[a-f\d]{6}|[a-f\d]{3}/i);
            if (!t3) return [0, 0, 0];
            let r2 = t3[0];
            3 === t3[0].length && (r2 = [...r2].map((e4) => e4 + e4).join(""));
            const n2 = Number.parseInt(r2, 16);
            return [n2 >> 16 & 255, n2 >> 8 & 255, 255 & n2];
          }, F.rgb.hcg = function(e3) {
            const t3 = e3[0] / 255, r2 = e3[1] / 255, n2 = e3[2] / 255, o2 = Math.max(Math.max(t3, r2), n2), a2 = Math.min(Math.min(t3, r2), n2), i2 = o2 - a2;
            let s2;
            return s2 = i2 <= 0 ? 0 : o2 === t3 ? (r2 - n2) / i2 % 6 : o2 === r2 ? 2 + (n2 - t3) / i2 : 4 + (t3 - r2) / i2, s2 /= 6, s2 %= 1, [360 * s2, 100 * i2, 100 * (i2 < 1 ? a2 / (1 - i2) : 0)];
          }, F.hsl.hcg = function(e3) {
            const t3 = e3[1] / 100, r2 = e3[2] / 100, n2 = r2 < 0.5 ? 2 * t3 * r2 : 2 * t3 * (1 - r2);
            let o2 = 0;
            return n2 < 1 && (o2 = (r2 - 0.5 * n2) / (1 - n2)), [e3[0], 100 * n2, 100 * o2];
          }, F.hsv.hcg = function(e3) {
            const t3 = e3[1] / 100, r2 = e3[2] / 100, n2 = t3 * r2;
            let o2 = 0;
            return n2 < 1 && (o2 = (r2 - n2) / (1 - n2)), [e3[0], 100 * n2, 100 * o2];
          }, F.hcg.rgb = function(e3) {
            const t3 = e3[0] / 360, r2 = e3[1] / 100, n2 = e3[2] / 100;
            if (0 === r2) return [255 * n2, 255 * n2, 255 * n2];
            const o2 = [0, 0, 0], a2 = t3 % 1 * 6, i2 = a2 % 1, s2 = 1 - i2;
            let l2 = 0;
            switch (Math.floor(a2)) {
              case 0:
                o2[0] = 1, o2[1] = i2, o2[2] = 0;
                break;
              case 1:
                o2[0] = s2, o2[1] = 1, o2[2] = 0;
                break;
              case 2:
                o2[0] = 0, o2[1] = 1, o2[2] = i2;
                break;
              case 3:
                o2[0] = 0, o2[1] = s2, o2[2] = 1;
                break;
              case 4:
                o2[0] = i2, o2[1] = 0, o2[2] = 1;
                break;
              default:
                o2[0] = 1, o2[1] = 0, o2[2] = s2;
            }
            return l2 = (1 - r2) * n2, [255 * (r2 * o2[0] + l2), 255 * (r2 * o2[1] + l2), 255 * (r2 * o2[2] + l2)];
          }, F.hcg.hsv = function(e3) {
            const t3 = e3[1] / 100, r2 = t3 + e3[2] / 100 * (1 - t3);
            let n2 = 0;
            return r2 > 0 && (n2 = t3 / r2), [e3[0], 100 * n2, 100 * r2];
          }, F.hcg.hsl = function(e3) {
            const t3 = e3[1] / 100, r2 = e3[2] / 100 * (1 - t3) + 0.5 * t3;
            let n2 = 0;
            return r2 > 0 && r2 < 0.5 ? n2 = t3 / (2 * r2) : r2 >= 0.5 && r2 < 1 && (n2 = t3 / (2 * (1 - r2))), [e3[0], 100 * n2, 100 * r2];
          }, F.hcg.hwb = function(e3) {
            const t3 = e3[1] / 100, r2 = t3 + e3[2] / 100 * (1 - t3);
            return [e3[0], 100 * (r2 - t3), 100 * (1 - r2)];
          }, F.hwb.hcg = function(e3) {
            const t3 = e3[1] / 100, r2 = 1 - e3[2] / 100, n2 = r2 - t3;
            let o2 = 0;
            return n2 < 1 && (o2 = (r2 - n2) / (1 - n2)), [e3[0], 100 * n2, 100 * o2];
          }, F.apple.rgb = function(e3) {
            return [e3[0] / 65535 * 255, e3[1] / 65535 * 255, e3[2] / 65535 * 255];
          }, F.rgb.apple = function(e3) {
            return [e3[0] / 255 * 65535, e3[1] / 255 * 65535, e3[2] / 255 * 65535];
          }, F.gray.rgb = function(e3) {
            return [e3[0] / 100 * 255, e3[0] / 100 * 255, e3[0] / 100 * 255];
          }, F.gray.hsl = function(e3) {
            return [0, 0, e3[0]];
          }, F.gray.hsv = F.gray.hsl, F.gray.hwb = function(e3) {
            return [0, 100, e3[0]];
          }, F.gray.cmyk = function(e3) {
            return [0, 0, 0, e3[0]];
          }, F.gray.lab = function(e3) {
            return [e3[0], 0, 0];
          }, F.gray.hex = function(e3) {
            const t3 = 255 & Math.round(e3[0] / 100 * 255), r2 = ((t3 << 16) + (t3 << 8) + t3).toString(16).toUpperCase();
            return "000000".slice(r2.length) + r2;
          }, F.rgb.gray = function(e3) {
            return [(e3[0] + e3[1] + e3[2]) / 3 / 255 * 100];
          };
          const Y = function(e3) {
            const t3 = function(e4) {
              const t4 = function() {
                const e5 = {}, t5 = Object.keys(I);
                for (let { length: r4 } = t5, n3 = 0; n3 < r4; n3++) e5[t5[n3]] = { distance: -1, parent: null };
                return e5;
              }(), r3 = [e4];
              for (t4[e4].distance = 0; r3.length > 0; ) {
                const e5 = r3.pop(), n3 = Object.keys(I[e5]);
                for (let { length: o2 } = n3, a2 = 0; a2 < o2; a2++) {
                  const o3 = n3[a2], i2 = t4[o3];
                  -1 === i2.distance && (i2.distance = t4[e5].distance + 1, i2.parent = e5, r3.unshift(o3));
                }
              }
              return t4;
            }(e3), r2 = {}, n2 = Object.keys(t3);
            for (let { length: e4 } = n2, o2 = 0; o2 < e4; o2++) {
              const e5 = n2[o2];
              null !== t3[e5].parent && (r2[e5] = G(e5, t3));
            }
            return r2;
          }, U = {}, V = Object.keys(I);
          function J(e3) {
            const t3 = function(...t4) {
              const r2 = t4[0];
              return null == r2 ? r2 : (r2.length > 1 && (t4 = r2), e3(t4));
            };
            return "conversion" in e3 && (t3.conversion = e3.conversion), t3;
          }
          function X(e3) {
            const t3 = function(...t4) {
              const r2 = t4[0];
              if (null == r2) return r2;
              r2.length > 1 && (t4 = r2);
              const n2 = e3(t4);
              if ("object" == typeof n2) for (let { length: e4 } = n2, t5 = 0; t5 < e4; t5++) n2[t5] = Math.round(n2[t5]);
              return n2;
            };
            return "conversion" in e3 && (t3.conversion = e3.conversion), t3;
          }
          for (const e3 of V) {
            U[e3] = {}, Object.defineProperty(U[e3], "channels", { value: I[e3].channels }), Object.defineProperty(U[e3], "labels", { value: I[e3].labels });
            const t3 = Y(e3), r2 = Object.keys(t3);
            for (const n2 of r2) {
              const r3 = t3[n2];
              U[e3][n2] = X(r3), U[e3][n2].raw = J(r3);
            }
          }
          const K = U, Z = ["keyword", "gray", "hex"], Q = {};
          for (const e3 of Object.keys(K)) Q[[...K[e3].labels].sort().join("")] = e3;
          const ee = {};
          function te(e3, t3) {
            if (!(this instanceof te)) return new te(e3, t3);
            if (t3 && t3 in Z && (t3 = null), t3 && !(t3 in K)) throw new Error("Unknown model: " + t3);
            let r2, n2;
            if (null == e3) this.model = "rgb", this.color = [0, 0, 0], this.valpha = 1;
            else if (e3 instanceof te) this.model = e3.model, this.color = [...e3.color], this.valpha = e3.valpha;
            else if ("string" == typeof e3) {
              const t4 = P.get(e3);
              if (null === t4) throw new Error("Unable to parse color from string: " + e3);
              this.model = t4.model, n2 = K[this.model].channels, this.color = t4.value.slice(0, n2), this.valpha = "number" == typeof t4.value[n2] ? t4.value[n2] : 1;
            } else if (e3.length > 0) {
              this.model = t3 || "rgb", n2 = K[this.model].channels;
              const r3 = Array.prototype.slice.call(e3, 0, n2);
              this.color = ae(r3, n2), this.valpha = "number" == typeof e3[n2] ? e3[n2] : 1;
            } else if ("number" == typeof e3) this.model = "rgb", this.color = [e3 >> 16 & 255, e3 >> 8 & 255, 255 & e3], this.valpha = 1;
            else {
              this.valpha = 1;
              const t4 = Object.keys(e3);
              "alpha" in e3 && (t4.splice(t4.indexOf("alpha"), 1), this.valpha = "number" == typeof e3.alpha ? e3.alpha : 0);
              const n3 = t4.sort().join("");
              if (!(n3 in Q)) throw new Error("Unable to parse color from object: " + JSON.stringify(e3));
              this.model = Q[n3];
              const { labels: o2 } = K[this.model], a2 = [];
              for (r2 = 0; r2 < o2.length; r2++) a2.push(e3[o2[r2]]);
              this.color = ae(a2);
            }
            if (ee[this.model]) for (n2 = K[this.model].channels, r2 = 0; r2 < n2; r2++) {
              const e4 = ee[this.model][r2];
              e4 && (this.color[r2] = e4(this.color[r2]));
            }
            this.valpha = Math.max(0, Math.min(1, this.valpha)), Object.freeze && Object.freeze(this);
          }
          te.prototype = { toString() {
            return this.string();
          }, toJSON() {
            return this[this.model]();
          }, string(e3) {
            let t3 = this.model in P.to ? this : this.rgb();
            t3 = t3.round("number" == typeof e3 ? e3 : 1);
            const r2 = 1 === t3.valpha ? t3.color : [...t3.color, this.valpha];
            return P.to[t3.model](...r2);
          }, percentString(e3) {
            const t3 = this.rgb().round("number" == typeof e3 ? e3 : 1), r2 = 1 === t3.valpha ? t3.color : [...t3.color, this.valpha];
            return P.to.rgb.percent(...r2);
          }, array() {
            return 1 === this.valpha ? [...this.color] : [...this.color, this.valpha];
          }, object() {
            const e3 = {}, { channels: t3 } = K[this.model], { labels: r2 } = K[this.model];
            for (let n2 = 0; n2 < t3; n2++) e3[r2[n2]] = this.color[n2];
            return 1 !== this.valpha && (e3.alpha = this.valpha), e3;
          }, unitArray() {
            const e3 = this.rgb().color;
            return e3[0] /= 255, e3[1] /= 255, e3[2] /= 255, 1 !== this.valpha && e3.push(this.valpha), e3;
          }, unitObject() {
            const e3 = this.rgb().object();
            return e3.r /= 255, e3.g /= 255, e3.b /= 255, 1 !== this.valpha && (e3.alpha = this.valpha), e3;
          }, round(e3) {
            return e3 = Math.max(e3 || 0, 0), new te([...this.color.map(re(e3)), this.valpha], this.model);
          }, alpha(e3) {
            return void 0 !== e3 ? new te([...this.color, Math.max(0, Math.min(1, e3))], this.model) : this.valpha;
          }, red: ne("rgb", 0, oe(255)), green: ne("rgb", 1, oe(255)), blue: ne("rgb", 2, oe(255)), hue: ne(["hsl", "hsv", "hsl", "hwb", "hcg"], 0, (e3) => (e3 % 360 + 360) % 360), saturationl: ne("hsl", 1, oe(100)), lightness: ne("hsl", 2, oe(100)), saturationv: ne("hsv", 1, oe(100)), value: ne("hsv", 2, oe(100)), chroma: ne("hcg", 1, oe(100)), gray: ne("hcg", 2, oe(100)), white: ne("hwb", 1, oe(100)), wblack: ne("hwb", 2, oe(100)), cyan: ne("cmyk", 0, oe(100)), magenta: ne("cmyk", 1, oe(100)), yellow: ne("cmyk", 2, oe(100)), black: ne("cmyk", 3, oe(100)), x: ne("xyz", 0, oe(95.047)), y: ne("xyz", 1, oe(100)), z: ne("xyz", 2, oe(108.833)), l: ne("lab", 0, oe(100)), a: ne("lab", 1), b: ne("lab", 2), keyword(e3) {
            return void 0 !== e3 ? new te(e3) : K[this.model].keyword(this.color);
          }, hex(e3) {
            return void 0 !== e3 ? new te(e3) : P.to.hex(...this.rgb().round().color);
          }, hexa(e3) {
            if (void 0 !== e3) return new te(e3);
            const t3 = this.rgb().round().color;
            let r2 = Math.round(255 * this.valpha).toString(16).toUpperCase();
            return 1 === r2.length && (r2 = "0" + r2), P.to.hex(...t3) + r2;
          }, rgbNumber() {
            const e3 = this.rgb().color;
            return (255 & e3[0]) << 16 | (255 & e3[1]) << 8 | 255 & e3[2];
          }, luminosity() {
            const e3 = this.rgb().color, t3 = [];
            for (const [r2, n2] of e3.entries()) {
              const e4 = n2 / 255;
              t3[r2] = e4 <= 0.04045 ? e4 / 12.92 : ((e4 + 0.055) / 1.055) ** 2.4;
            }
            return 0.2126 * t3[0] + 0.7152 * t3[1] + 0.0722 * t3[2];
          }, contrast(e3) {
            const t3 = this.luminosity(), r2 = e3.luminosity();
            return t3 > r2 ? (t3 + 0.05) / (r2 + 0.05) : (r2 + 0.05) / (t3 + 0.05);
          }, level(e3) {
            const t3 = this.contrast(e3);
            return t3 >= 7 ? "AAA" : t3 >= 4.5 ? "AA" : "";
          }, isDark() {
            const e3 = this.rgb().color;
            return (2126 * e3[0] + 7152 * e3[1] + 722 * e3[2]) / 1e4 < 128;
          }, isLight() {
            return !this.isDark();
          }, negate() {
            const e3 = this.rgb();
            for (let t3 = 0; t3 < 3; t3++) e3.color[t3] = 255 - e3.color[t3];
            return e3;
          }, lighten(e3) {
            const t3 = this.hsl();
            return t3.color[2] += t3.color[2] * e3, t3;
          }, darken(e3) {
            const t3 = this.hsl();
            return t3.color[2] -= t3.color[2] * e3, t3;
          }, saturate(e3) {
            const t3 = this.hsl();
            return t3.color[1] += t3.color[1] * e3, t3;
          }, desaturate(e3) {
            const t3 = this.hsl();
            return t3.color[1] -= t3.color[1] * e3, t3;
          }, whiten(e3) {
            const t3 = this.hwb();
            return t3.color[1] += t3.color[1] * e3, t3;
          }, blacken(e3) {
            const t3 = this.hwb();
            return t3.color[2] += t3.color[2] * e3, t3;
          }, grayscale() {
            const e3 = this.rgb().color, t3 = 0.3 * e3[0] + 0.59 * e3[1] + 0.11 * e3[2];
            return te.rgb(t3, t3, t3);
          }, fade(e3) {
            return this.alpha(this.valpha - this.valpha * e3);
          }, opaquer(e3) {
            return this.alpha(this.valpha + this.valpha * e3);
          }, rotate(e3) {
            const t3 = this.hsl();
            let r2 = t3.color[0];
            return r2 = (r2 + e3) % 360, r2 = r2 < 0 ? 360 + r2 : r2, t3.color[0] = r2, t3;
          }, mix(e3, t3) {
            if (!e3 || !e3.rgb) throw new Error('Argument to "mix" was not a Color instance, but rather an instance of ' + typeof e3);
            const r2 = e3.rgb(), n2 = this.rgb(), o2 = void 0 === t3 ? 0.5 : t3, a2 = 2 * o2 - 1, i2 = r2.alpha() - n2.alpha(), s2 = ((a2 * i2 === -1 ? a2 : (a2 + i2) / (1 + a2 * i2)) + 1) / 2, l2 = 1 - s2;
            return te.rgb(s2 * r2.red() + l2 * n2.red(), s2 * r2.green() + l2 * n2.green(), s2 * r2.blue() + l2 * n2.blue(), r2.alpha() * o2 + n2.alpha() * (1 - o2));
          } };
          for (const e3 of Object.keys(K)) {
            if (Z.includes(e3)) continue;
            const { channels: t3 } = K[e3];
            te.prototype[e3] = function(...t4) {
              return this.model === e3 ? new te(this) : t4.length > 0 ? new te(t4, e3) : new te([...(r2 = K[this.model][e3].raw(this.color), Array.isArray(r2) ? r2 : [r2]), this.valpha], e3);
              var r2;
            }, te[e3] = function(...r2) {
              let n2 = r2[0];
              return "number" == typeof n2 && (n2 = ae(r2, t3)), new te(n2, e3);
            };
          }
          function re(e3) {
            return function(t3) {
              return function(e4, t4) {
                return Number(e4.toFixed(t4));
              }(t3, e3);
            };
          }
          function ne(e3, t3, r2) {
            e3 = Array.isArray(e3) ? e3 : [e3];
            for (const n2 of e3) (ee[n2] || (ee[n2] = []))[t3] = r2;
            return e3 = e3[0], function(n2) {
              let o2;
              return void 0 !== n2 ? (r2 && (n2 = r2(n2)), o2 = this[e3](), o2.color[t3] = n2, o2) : (o2 = this[e3]().color[t3], r2 && (o2 = r2(o2)), o2);
            };
          }
          function oe(e3) {
            return function(t3) {
              return Math.max(0, Math.min(e3, t3));
            };
          }
          function ae(e3, t3) {
            for (let r2 = 0; r2 < t3; r2++) "number" != typeof e3[r2] && (e3[r2] = 0);
            return e3;
          }
          const ie = te, se = { aliceblue: [240, 248, 255], antiquewhite: [250, 235, 215], aqua: [0, 255, 255], aquamarine: [127, 255, 212], azure: [240, 255, 255], beige: [245, 245, 220], bisque: [255, 228, 196], black: [0, 0, 0], blanchedalmond: [255, 235, 205], blue: [0, 0, 255], blueviolet: [138, 43, 226], brown: [165, 42, 42], burlywood: [222, 184, 135], cadetblue: [95, 158, 160], chartreuse: [127, 255, 0], chocolate: [210, 105, 30], coral: [255, 127, 80], cornflowerblue: [100, 149, 237], cornsilk: [255, 248, 220], crimson: [220, 20, 60], cyan: [0, 255, 255], darkblue: [0, 0, 139], darkcyan: [0, 139, 139], darkgoldenrod: [184, 134, 11], darkgray: [169, 169, 169], darkgreen: [0, 100, 0], darkgrey: [169, 169, 169], darkkhaki: [189, 183, 107], darkmagenta: [139, 0, 139], darkolivegreen: [85, 107, 47], darkorange: [255, 140, 0], darkorchid: [153, 50, 204], darkred: [139, 0, 0], darksalmon: [233, 150, 122], darkseagreen: [143, 188, 143], darkslateblue: [72, 61, 139], darkslategray: [47, 79, 79], darkslategrey: [47, 79, 79], darkturquoise: [0, 206, 209], darkviolet: [148, 0, 211], deeppink: [255, 20, 147], deepskyblue: [0, 191, 255], dimgray: [105, 105, 105], dimgrey: [105, 105, 105], dodgerblue: [30, 144, 255], firebrick: [178, 34, 34], floralwhite: [255, 250, 240], forestgreen: [34, 139, 34], fuchsia: [255, 0, 255], gainsboro: [220, 220, 220], ghostwhite: [248, 248, 255], gold: [255, 215, 0], goldenrod: [218, 165, 32], gray: [128, 128, 128], green: [0, 128, 0], greenyellow: [173, 255, 47], grey: [128, 128, 128], honeydew: [240, 255, 240], hotpink: [255, 105, 180], indianred: [205, 92, 92], indigo: [75, 0, 130], ivory: [255, 255, 240], khaki: [240, 230, 140], lavender: [230, 230, 250], lavenderblush: [255, 240, 245], lawngreen: [124, 252, 0], lemonchiffon: [255, 250, 205], lightblue: [173, 216, 230], lightcoral: [240, 128, 128], lightcyan: [224, 255, 255], lightgoldenrodyellow: [250, 250, 210], lightgray: [211, 211, 211], lightgreen: [144, 238, 144], lightgrey: [211, 211, 211], lightpink: [255, 182, 193], lightsalmon: [255, 160, 122], lightseagreen: [32, 178, 170], lightskyblue: [135, 206, 250], lightslategray: [119, 136, 153], lightslategrey: [119, 136, 153], lightsteelblue: [176, 196, 222], lightyellow: [255, 255, 224], lime: [0, 255, 0], limegreen: [50, 205, 50], linen: [250, 240, 230], magenta: [255, 0, 255], maroon: [128, 0, 0], mediumaquamarine: [102, 205, 170], mediumblue: [0, 0, 205], mediumorchid: [186, 85, 211], mediumpurple: [147, 112, 219], mediumseagreen: [60, 179, 113], mediumslateblue: [123, 104, 238], mediumspringgreen: [0, 250, 154], mediumturquoise: [72, 209, 204], mediumvioletred: [199, 21, 133], midnightblue: [25, 25, 112], mintcream: [245, 255, 250], mistyrose: [255, 228, 225], moccasin: [255, 228, 181], navajowhite: [255, 222, 173], navy: [0, 0, 128], oldlace: [253, 245, 230], olive: [128, 128, 0], olivedrab: [107, 142, 35], orange: [255, 165, 0], orangered: [255, 69, 0], orchid: [218, 112, 214], palegoldenrod: [238, 232, 170], palegreen: [152, 251, 152], paleturquoise: [175, 238, 238], palevioletred: [219, 112, 147], papayawhip: [255, 239, 213], peachpuff: [255, 218, 185], peru: [205, 133, 63], pink: [255, 192, 203], plum: [221, 160, 221], powderblue: [176, 224, 230], purple: [128, 0, 128], rebeccapurple: [102, 51, 153], red: [255, 0, 0], rosybrown: [188, 143, 143], royalblue: [65, 105, 225], saddlebrown: [139, 69, 19], salmon: [250, 128, 114], sandybrown: [244, 164, 96], seagreen: [46, 139, 87], seashell: [255, 245, 238], sienna: [160, 82, 45], silver: [192, 192, 192], skyblue: [135, 206, 235], slateblue: [106, 90, 205], slategray: [112, 128, 144], slategrey: [112, 128, 144], snow: [255, 250, 250], springgreen: [0, 255, 127], steelblue: [70, 130, 180], tan: [210, 180, 140], teal: [0, 128, 128], thistle: [216, 191, 216], tomato: [255, 99, 71], turquoise: [64, 224, 208], violet: [238, 130, 238], wheat: [245, 222, 179], white: [255, 255, 255], whitesmoke: [245, 245, 245], yellow: [255, 255, 0], yellowgreen: [154, 205, 50] };
          for (const e3 in se) Object.freeze(se[e3]);
          const le = Object.freeze(se);
          function ce(e3, t3, r2) {
            return { r: 255 * r2(e3.r / 255, t3.r / 255), g: 255 * r2(e3.g / 255, t3.g / 255), b: 255 * r2(e3.b / 255, t3.b / 255) };
          }
          function ue(e3, t3) {
            return t3;
          }
          function he(e3, t3) {
            return e3 * t3;
          }
          function fe(e3, t3) {
            return e3 + t3 - e3 * t3;
          }
          function pe(e3, t3) {
            return ye(t3, e3);
          }
          function de(e3, t3) {
            return Math.min(e3, t3);
          }
          function ge(e3, t3) {
            return Math.min(Math.max(e3, t3), 1);
          }
          function me(e3, t3) {
            return 0 === e3 ? 0 : 1 === t3 ? 1 : Math.min(1, e3 / (1 - t3));
          }
          function be(e3, t3) {
            return 1 === e3 ? 1 : 0 === t3 ? 0 : 1 - Math.min(1, (1 - e3) / t3);
          }
          function ye(e3, t3) {
            return t3 <= 0.5 ? he(e3, 2 * t3) : fe(e3, 2 * t3 - 1);
          }
          function we(e3, t3) {
            return t3 <= 0.5 ? e3 - (1 - 2 * t3) * e3 * (1 - e3) : e3 + (2 * t3 - 1) * ((e3 <= 0.25 ? ((16 * e3 - 12) * e3 + 4) * e3 : Math.sqrt(e3)) - e3);
          }
          function ve(e3, t3) {
            return Math.abs(e3 - t3);
          }
          function ke(e3, t3) {
            return e3 + t3 - 2 * e3 * t3;
          }
          function _e(e3, t3, r2) {
            return Math.min(Math.max(e3 || 0, t3), r2);
          }
          function Me(e3) {
            return { r: _e(e3.r, 0, 255), g: _e(e3.g, 0, 255), b: _e(e3.b, 0, 255), a: _e(e3.a, 0, 1) };
          }
          function Se(e3) {
            return { r: 255 * e3.r, g: 255 * e3.g, b: 255 * e3.b, a: e3.a };
          }
          function Ee(e3) {
            return { r: e3.r / 255, g: e3.g / 255, b: e3.b / 255, a: e3.a };
          }
          function Ce(e3, t3) {
            void 0 === t3 && (t3 = 0);
            var r2 = Math.pow(10, t3);
            return { r: Math.round(e3.r * r2) / r2, g: Math.round(e3.g * r2) / r2, b: Math.round(e3.b * r2) / r2, a: e3.a };
          }
          function xe(e3, t3, r2, n2, o2, a2) {
            return (1 - t3 / r2) * n2 + t3 / r2 * Math.round((1 - e3) * o2 + e3 * a2);
          }
          function Oe(e3, t3, r2, n2, o2) {
            void 0 === o2 && (o2 = { unitInput: false, unitOutput: false, roundOutput: true }), o2.unitInput && (e3 = Se(e3), t3 = Se(t3)), e3 = Me(e3);
            var a2 = (t3 = Me(t3)).a + e3.a - t3.a * e3.a, i2 = r2(e3, t3, n2), s2 = Me({ r: xe(e3.a, t3.a, a2, e3.r, t3.r, i2.r), g: xe(e3.a, t3.a, a2, e3.g, t3.g, i2.g), b: xe(e3.a, t3.a, a2, e3.b, t3.b, i2.b), a: a2 });
            return s2 = o2.unitOutput ? Ee(s2) : o2.roundOutput ? Ce(s2) : function(e4) {
              return Ce(e4, 9);
            }(s2), s2;
          }
          function je(e3, t3, r2) {
            return Se(r2(Ee(e3), Ee(t3)));
          }
          function Re(e3) {
            return 0.3 * e3.r + 0.59 * e3.g + 0.11 * e3.b;
          }
          function Ae(e3, t3) {
            var r2 = t3 - Re(e3);
            return function(e4) {
              var t4 = Re(e4), r3 = e4.r, n2 = e4.g, o2 = e4.b, a2 = Math.min(r3, n2, o2), i2 = Math.max(r3, n2, o2);
              function s2(e5) {
                return t4 + (e5 - t4) * t4 / (t4 - a2);
              }
              function l2(e5) {
                return t4 + (e5 - t4) * (1 - t4) / (i2 - t4);
              }
              return a2 < 0 && (r3 = s2(r3), n2 = s2(n2), o2 = s2(o2)), i2 > 1 && (r3 = l2(r3), n2 = l2(n2), o2 = l2(o2)), { r: r3, g: n2, b: o2 };
            }({ r: e3.r + r2, g: e3.g + r2, b: e3.b + r2 });
          }
          function Te(e3) {
            return Math.max(e3.r, e3.g, e3.b) - Math.min(e3.r, e3.g, e3.b);
          }
          function Be(e3, t3) {
            var r2 = ["r", "g", "b"].sort(function(t4, r3) {
              return e3[t4] - e3[r3];
            }), n2 = r2[0], o2 = r2[1], a2 = r2[2], i2 = { r: e3.r, g: e3.g, b: e3.b };
            return i2[a2] > i2[n2] ? (i2[o2] = (i2[o2] - i2[n2]) * t3 / (i2[a2] - i2[n2]), i2[a2] = t3) : i2[o2] = i2[a2] = 0, i2[n2] = 0, i2;
          }
          function Pe(e3, t3) {
            return Ae(Be(t3, Te(e3)), Re(e3));
          }
          function Ne(e3, t3) {
            return Ae(Be(e3, Te(t3)), Re(e3));
          }
          function Le(e3, t3) {
            return Ae(t3, Re(e3));
          }
          function De(e3, t3) {
            return Ae(e3, Re(t3));
          }
          function Fe(e3, t3) {
            return Oe(e3, t3, ce, ue);
          }
          function Ie(e3, t3) {
            return Oe(e3, t3, ce, he);
          }
          function $e(e3, t3) {
            return Oe(e3, t3, ce, fe);
          }
          function ze(e3, t3) {
            return Oe(e3, t3, ce, pe);
          }
          function qe(e3, t3) {
            return Oe(e3, t3, ce, de);
          }
          function He(e3, t3) {
            return Oe(e3, t3, ce, ge);
          }
          function We(e3, t3) {
            return Oe(e3, t3, ce, me);
          }
          function Ge(e3, t3) {
            return Oe(e3, t3, ce, be);
          }
          function Ye(e3, t3) {
            return Oe(e3, t3, ce, ye);
          }
          function Ue(e3, t3) {
            return Oe(e3, t3, ce, we);
          }
          function Ve(e3, t3) {
            return Oe(e3, t3, ce, ve);
          }
          function Je(e3, t3) {
            return Oe(e3, t3, ce, ke);
          }
          function Xe(e3, t3) {
            return Oe(e3, t3, je, Pe);
          }
          function Ke(e3, t3) {
            return Oe(e3, t3, je, Ne);
          }
          function Ze(e3, t3) {
            return Oe(e3, t3, je, Le);
          }
          function Qe(e3, t3) {
            return Oe(e3, t3, je, De);
          }
          function et(e3, t3) {
            let r2, n2, o2 = e3.length, a2 = false, i2 = false;
            Array.isArray(e3[0]) ? r2 = e3 : (r2 = [e3], o2 = r2.length, a2 = true), Array.isArray(t3[0]) ? n2 = t3 : (n2 = t3.length > 0 ? t3.map((e4) => [e4]) : [[]], i2 = true);
            let s2 = n2[0].length, l2 = n2[0].map((e4, t4) => n2.map((e5) => e5[t4])), c2 = r2.map((e4) => l2.map((t4) => {
              let r3 = 0;
              if (!Array.isArray(e4)) {
                for (let n3 of t4) r3 += e4 * n3;
                return r3;
              }
              for (let n3 = 0; n3 < e4.length; n3++) r3 += e4[n3] * (t4[n3] || 0);
              return r3;
            }));
            return 1 === o2 && a2 && (c2 = c2[0]), 1 === s2 && i2 ? 1 === o2 && a2 ? c2[0] : c2.map((e4) => e4[0]) : c2;
          }
          function tt(e3, t3) {
            return e3[0] * t3[0] + e3[1] * t3[1] + e3[2] * t3[2];
          }
          function rt(e3, t3, r2 = [0, 0, 0]) {
            const n2 = tt(e3, t3[0]), o2 = tt(e3, t3[1]), a2 = tt(e3, t3[2]);
            return r2[0] = n2, r2[1] = o2, r2[2] = a2, r2;
          }
          function nt(e3) {
            return "string" === ot(e3);
          }
          function ot(e3) {
            return (Object.prototype.toString.call(e3).match(/^\[object\s+(.*?)\]$/)[1] || "").toLowerCase();
          }
          function at(e3, { precision: t3 = 16, unit: r2 }) {
            return it(e3) ? "none" : (e3 = +lt(e3, t3)) + (r2 != null ? r2 : "");
          }
          function it(e3) {
            return null === e3;
          }
          function st(e3) {
            return it(e3) ? 0 : e3;
          }
          function lt(e3, t3) {
            if (0 === e3) return 0;
            let r2 = ~~e3, n2 = 0;
            r2 && t3 && (n2 = 1 + ~~Math.log10(Math.abs(r2)));
            const o2 = 10 ** (t3 - n2);
            return Math.floor(e3 * o2 + 0.5) / o2;
          }
          function ct(e3, t3, r2) {
            return isNaN(e3) ? t3 : isNaN(t3) ? e3 : e3 + (t3 - e3) * r2;
          }
          function ut(e3, t3, r2) {
            return (r2 - e3) / (t3 - e3);
          }
          function ht(e3, t3, r2) {
            return !e3 || !t3 || e3 === t3 || e3[0] === t3[0] && e3[1] === t3[1] || isNaN(r2) || null === r2 ? r2 : ct(t3[0], t3[1], ut(e3[0], e3[1], r2));
          }
          function ft(e3, t3, r2) {
            return Math.max(Math.min(r2, t3), e3);
          }
          function pt(e3, t3) {
            return Math.sign(e3) === Math.sign(t3) ? e3 : -e3;
          }
          function dt(e3, t3) {
            return pt(Math.abs(e3) ** t3, e3);
          }
          function gt(e3, t3) {
            return 0 === t3 ? 0 : e3 / t3;
          }
          function mt(e3, t3, r2 = 0, n2 = e3.length) {
            for (; r2 < n2; ) {
              const o2 = r2 + n2 >> 1;
              e3[o2] < t3 ? r2 = o2 + 1 : n2 = o2;
            }
            return r2;
          }
          function bt(e3, t3) {
            var _a3;
            if (e3 instanceof t3) return true;
            const r2 = t3.name;
            for (; e3; ) {
              const t4 = Object.getPrototypeOf(e3), n2 = (_a3 = t4 == null ? void 0 : t4.constructor) == null ? void 0 : _a3.name;
              if (n2 === r2) return true;
              if (!n2 || "Object" === n2) return false;
              e3 = t4;
            }
            return false;
          }
          var yt = Object.freeze({ __proto__: null, bisectLeft: mt, clamp: ft, copySign: pt, interpolate: ct, interpolateInv: ut, isInstance: bt, isNone: it, isString: nt, mapRange: ht, multiplyMatrices: et, multiply_v3_m3x3: rt, serializeNumber: at, skipNone: st, spow: dt, toPrecision: lt, type: ot, zdiv: gt });
          const wt = new class {
            add(e3, t3, r2) {
              if ("string" == typeof arguments[0]) (Array.isArray(e3) ? e3 : [e3]).forEach(function(e4) {
                this[e4] = this[e4] || [], t3 && this[e4][r2 ? "unshift" : "push"](t3);
              }, this);
              else for (var e3 in arguments[0]) this.add(e3, arguments[0][e3], arguments[1]);
            }
            run(e3, t3) {
              this[e3] = this[e3] || [], this[e3].forEach(function(e4) {
                e4.call(t3 && t3.context ? t3.context : t3, t3);
              });
            }
          }();
          var vt = { gamut_mapping: "css", precision: 5, deltaE: "76", verbose: "test" !== ((_d = (_c = (_b = globalThis == null ? void 0 : globalThis.process) == null ? void 0 : _b.env) == null ? void 0 : _c.NODE_ENV) == null ? void 0 : _d.toLowerCase()), warn: function(e3) {
            var _a3, _b2;
            this.verbose && ((_b2 = (_a3 = globalThis == null ? void 0 : globalThis.console) == null ? void 0 : _a3.warn) == null ? void 0 : _b2.call(_a3, e3));
          } };
          class kt {
            constructor(e3, t3) {
              __publicField(this, "type");
              __publicField(this, "coordMeta");
              __publicField(this, "coordRange");
              __publicField(this, "range");
              var _a3;
              if ("object" == typeof e3 && (this.coordMeta = e3), t3 && (this.coordMeta = t3, this.coordRange = (_a3 = t3.range) != null ? _a3 : t3.refRange), "string" == typeof e3) {
                let t4 = e3.trim().match(new RegExp("^(?<type><[a-z]+>)(\\[(?<min>-?[.\\d]+),\\s*(?<max>-?[.\\d]+)\\])?$"));
                if (!t4) throw new TypeError(`Cannot parse ${e3} as a type definition.`);
                this.type = t4.groups.type;
                let { min: r2, max: n2 } = t4.groups;
                (r2 || n2) && (this.range = [+r2, +n2]);
              }
            }
            get computedRange() {
              return this.range ? this.range : "<percentage>" === this.type ? this.percentageRange() : "<angle>" === this.type ? [0, 360] : null;
            }
            get unit() {
              return "<percentage>" === this.type ? "%" : "<angle>" === this.type ? "deg" : "";
            }
            resolve(e3) {
              if ("<angle>" === this.type) return e3;
              let t3 = this.computedRange, r2 = this.coordRange;
              return "<percentage>" === this.type && (r2 != null ? r2 : r2 = this.percentageRange()), ht(t3, r2, e3);
            }
            serialize(e3, t3) {
              let r2 = "<percentage>" === this.type ? this.percentageRange(100) : this.computedRange, n2 = this.unit;
              return at(e3 = ht(this.coordRange, r2, e3), { unit: n2, precision: t3 });
            }
            toString() {
              let e3 = this.type;
              if (this.range) {
                let [t3 = "", r2 = ""] = this.range;
                e3 += `[${t3},${r2}]`;
              }
              return e3;
            }
            percentageRange(e3 = 1) {
              let t3;
              return t3 = this.coordMeta && this.coordMeta.range || this.coordRange && this.coordRange[0] >= 0 ? [0, 1] : [-1, 1], [t3[0] * e3, t3[1] * e3];
            }
            static get(e3, t3) {
              return bt(e3, this) ? e3 : new this(e3, t3);
            }
          }
          const _t = Symbol("instance");
          class Mt {
            constructor(e3, t3 = e3.space) {
              __publicField(this, "type");
              __publicField(this, "name");
              __publicField(this, "spaceCoords");
              __publicField(this, "coords");
              __publicField(this, "id");
              __publicField(this, "alpha");
              e3[_t] = this, this.type = "function", this.name = "color", Object.assign(this, e3), this.space = t3, "custom" !== this.type && (this.spaceCoords = Object.values(t3.coords), this.coords || (this.coords = this.spaceCoords.map((e4) => {
                let t4 = ["<number>", "<percentage>"];
                return "angle" === e4.type && t4.push("<angle>"), t4;
              })), this.coords = this.coords.map((e4, t4) => {
                let r2 = this.spaceCoords[t4];
                return "string" == typeof e4 && (e4 = e4.trim().split(/\s*\|\s*/)), e4.map((e5) => kt.get(e5, r2));
              }));
            }
            serializeCoords(e3, t3, r2) {
              return r2 = e3.map((e4, t4) => {
                var _a3;
                return kt.get((_a3 = r2 == null ? void 0 : r2[t4]) != null ? _a3 : this.coords[t4][0], this.spaceCoords[t4]);
              }), e3.map((e4, n2) => r2[n2].serialize(e4, t3));
            }
            coerceCoords(e3, t3) {
              return Object.entries(this.space.coords).map(([r2, n2], o2) => {
                var _a3;
                let a2 = e3[o2];
                if (it(a2) || isNaN(a2)) return a2;
                let i2 = t3[o2], s2 = this.coords[o2].find((e4) => e4.type == i2);
                if (!s2) {
                  let e4 = n2.name || r2;
                  throw new TypeError(`${(_a3 = i2 != null ? i2 : a2 == null ? void 0 : a2.raw) != null ? _a3 : a2} not allowed for ${e4} in ${this.name}()`);
                }
                return a2 = s2.resolve(a2), s2.range && (t3[o2] = s2.toString()), a2;
              });
            }
            canSerialize() {
              return "function" === this.type || this.serialize;
            }
            parse(e3) {
              return null;
            }
            static get(e3, ...t3) {
              return !e3 || bt(e3, this) ? e3 : e3[_t] ? e3[_t] : new Mt(e3, ...t3);
            }
          }
          const St = { D50: [0.3457 / 0.3585, 1, 0.2958 / 0.3585], D65: [0.3127 / 0.329, 1, 0.3583 / 0.329] };
          function Et(e3) {
            return Array.isArray(e3) ? e3 : St[e3];
          }
          function Ct(e3, t3, r2, n2 = {}) {
            if (e3 = Et(e3), t3 = Et(t3), !e3 || !t3) throw new TypeError(`Missing white point to convert ${e3 ? "" : "from"}${e3 || t3 ? "" : "/"}${t3 ? "" : "to"}`);
            if (e3 === t3) return r2;
            let o2 = { W1: e3, W2: t3, XYZ: r2, options: n2 };
            if (wt.run("chromatic-adaptation-start", o2), o2.M || (o2.W1 === St.D65 && o2.W2 === St.D50 ? o2.M = [[1.0479297925449969, 0.022946870601609652, -0.05019226628920524], [0.02962780877005599, 0.9904344267538799, -0.017073799063418826], [-0.009243040646204504, 0.015055191490298152, 0.7518742814281371]] : o2.W1 === St.D50 && o2.W2 === St.D65 && (o2.M = [[0.955473421488075, -0.02309845494876471, 0.06325924320057072], [-0.0283697093338637, 1.0099953980813041, 0.021041441191917323], [0.012314014864481998, -0.020507649298898964, 1.330365926242124]])), wt.run("chromatic-adaptation-end", o2), o2.M) return rt(o2.XYZ, o2.M);
            throw new TypeError("Only Bradford CAT with white points D50 and D65 supported for now.");
          }
          function xt(e3, t3) {
            var _a3, _b2, _c2, _d2;
            let r2, n2 = { str: (_a3 = String(e3)) == null ? void 0 : _a3.trim(), options: t3 };
            if (wt.run("parse-start", n2), n2.color) return n2.color;
            n2.parsed = function(e4) {
              if (!e4) return;
              let t4 = (e4 = e4.trim()).match(jt.function);
              if (t4) {
                let e5 = [], r3 = [], n3 = false, o3 = t4[1].toLowerCase(), a2 = t4[2].replace(jt.singleArgument, (t5, a3) => {
                  let { value: i2, meta: s2 } = function(e6) {
                    var _a4;
                    let t6 = {}, r4 = (_a4 = e6.match(jt.unitValue)) == null ? void 0 : _a4[0], n4 = t6.raw = e6;
                    return r4 ? (t6.type = "%" === r4 ? "<percentage>" : "<angle>", t6.unit = r4, t6.unitless = Number(n4.slice(0, -r4.length)), n4 = t6.unitless * Ot[r4]) : jt.number.test(n4) ? (n4 = Number(n4), t6.type = "<number>") : "none" === n4 ? n4 = null : "NaN" === n4 || "calc(NaN)" === n4 ? (n4 = NaN, t6.type = "<number>") : t6.type = "<ident>", { value: n4, meta: t6 };
                  }(a3);
                  return (t5.startsWith("/") || "color" !== o3 && 3 === e5.length) && (n3 = true), e5.push(i2), r3.push(s2), "";
                });
                return { name: o3, args: e5, argMeta: r3, lastAlpha: n3, commas: a2.includes(","), rawName: t4[1], rawArgs: t4[2] };
              }
            }(n2.str);
            let o2 = n2.options ? (_b2 = n2.options.parseMeta) != null ? _b2 : n2.options.meta : null;
            if (n2.parsed) {
              let t4, a2, i2 = n2.parsed.name, s2 = n2.parsed.args, l2 = s2.map((e4, t5) => {
                var _a4;
                return (_a4 = n2.parsed.argMeta[t5]) == null ? void 0 : _a4.type;
              });
              if ("color" === i2) {
                let r3 = s2.shift();
                l2.shift();
                let o3 = r3.startsWith("--") ? r3.substring(2) : `--${r3}`, c3 = [r3, o3];
                if (t4 = At.findFormat({ name: i2, id: c3, type: "function" }), !t4) {
                  let t5, a3 = r3 in At.registry ? r3 : o3;
                  if (a3 in At.registry) {
                    let n3 = (_d2 = (_c2 = At.registry[a3].formats) == null ? void 0 : _c2.color) == null ? void 0 : _d2.id;
                    n3 && (t5 = `Did you mean ${e3.replace("color(" + r3, "color(" + n3)}?`);
                  }
                  throw new TypeError(`Cannot parse ${n2.str}. ` + (t5 != null ? t5 : "Missing a plugin?"));
                }
                a2 = t4.space, t4.id.startsWith("--") && !r3.startsWith("--") && vt.warn(`${a2.name} is a non-standard space and not currently supported in the CSS spec. Use prefixed color(${t4.id}) instead of color(${r3}).`), r3.startsWith("--") && !t4.id.startsWith("--") && vt.warn(`${a2.name} is a standard space and supported in the CSS spec. Use color(${t4.id}) instead of prefixed color(${r3}).`);
              } else t4 = At.findFormat({ name: i2, type: "function" }), a2 = t4.space;
              o2 && Object.assign(o2, { format: t4, formatId: t4.name, types: l2, commas: n2.parsed.commas });
              let c2 = 1;
              n2.parsed.lastAlpha && (c2 = n2.parsed.args.pop(), o2 && (o2.alphaType = l2.pop()));
              let u2 = t4.coords.length;
              if (s2.length !== u2) throw new TypeError(`Expected ${u2} coordinates for ${a2.id} in ${n2.str}), got ${s2.length}`);
              s2 = t4.coerceCoords(s2, l2), r2 = { spaceId: a2.id, coords: s2, alpha: c2 };
            } else e: for (let e4 of At.all) for (let t4 in e4.formats) {
              let a2 = e4.formats[t4];
              if ("custom" !== a2.type) continue;
              if (a2.test && !a2.test(n2.str)) continue;
              let i2 = e4.getFormat(a2), s2 = i2.parse(n2.str);
              if (s2) {
                o2 && Object.assign(o2, { format: i2, formatId: t4 }), r2 = s2;
                break e;
              }
            }
            if (!r2) throw new TypeError(`Could not parse ${e3} as a color. Missing a plugin?`);
            return r2.alpha = it(r2.alpha) ? r2.alpha : void 0 === r2.alpha ? 1 : ft(0, r2.alpha, 1), r2;
          }
          const Ot = { "%": 0.01, deg: 1, grad: 0.9, rad: 180 / Math.PI, turn: 360 }, jt = { function: /^([a-z]+)\(((?:calc\(NaN\)|.)+?)\)$/i, number: /^([-+]?(?:[0-9]*\.)?[0-9]+(e[-+]?[0-9]+)?)$/i, unitValue: RegExp(`(${Object.keys(Ot).join("|")})$`), singleArgument: /\/?\s*(none|NaN|calc\(NaN\)|[-+\w.]+(?:%|deg|g?rad|turn)?)/g };
          function Rt(e3, t3) {
            if (Array.isArray(e3)) return e3.map((e4) => Rt(e4, t3));
            if (!e3) throw new TypeError("Empty color reference");
            nt(e3) && (e3 = xt(e3, t3));
            let r2 = e3.space || e3.spaceId;
            return "string" == typeof r2 && (e3.space = At.get(r2)), void 0 === e3.alpha && (e3.alpha = 1), e3;
          }
          const _At = class _At {
            constructor(e3) {
              var _a3, _b2, _c2, _d2, _e2, _f;
              this.id = e3.id, this.name = e3.name, this.base = e3.base ? _At.get(e3.base) : null, this.aliases = e3.aliases, this.base && (this.fromBase = e3.fromBase, this.toBase = e3.toBase);
              let t3 = (_a3 = e3.coords) != null ? _a3 : this.base.coords;
              for (let e4 in t3) "name" in t3[e4] || (t3[e4].name = e4);
              this.coords = t3;
              let r2 = (_c2 = (_b2 = e3.white) != null ? _b2 : this.base.white) != null ? _c2 : "D65";
              this.white = Et(r2), this.formats = (_d2 = e3.formats) != null ? _d2 : {};
              for (let e4 in this.formats) {
                let t4 = this.formats[e4];
                t4.type || (t4.type = "function"), t4.name || (t4.name = e4);
              }
              ((_e2 = this.formats.color) == null ? void 0 : _e2.id) || (this.formats.color = __spreadProps(__spreadValues({}, (_f = this.formats.color) != null ? _f : {}), { id: e3.cssId || this.id })), e3.gamutSpace ? this.gamutSpace = "self" === e3.gamutSpace ? this : _At.get(e3.gamutSpace) : this.isPolar ? this.gamutSpace = this.base : this.gamutSpace = this, this.gamutSpace.isUnbounded && (this.inGamut = (e4, t4) => true), this.referred = e3.referred, Object.defineProperty(this, "path", { value: Tt(this).reverse(), writable: false, enumerable: true, configurable: true }), wt.run("colorspace-init-end", this);
            }
            inGamut(e3, { epsilon: t3 = 75e-6 } = {}) {
              if (!this.equals(this.gamutSpace)) return e3 = this.to(this.gamutSpace, e3), this.gamutSpace.inGamut(e3, { epsilon: t3 });
              let r2 = Object.values(this.coords);
              return e3.every((e4, n2) => {
                let o2 = r2[n2];
                if ("angle" !== o2.type && o2.range) {
                  if (it(e4)) return true;
                  let [r3, n3] = o2.range;
                  return (void 0 === r3 || e4 >= r3 - t3) && (void 0 === n3 || e4 <= n3 + t3);
                }
                return true;
              });
            }
            get isUnbounded() {
              return Object.values(this.coords).every((e3) => !("range" in e3));
            }
            get cssId() {
              var _a3, _b2;
              return ((_b2 = (_a3 = this.formats) == null ? void 0 : _a3.color) == null ? void 0 : _b2.id) || this.id;
            }
            get isPolar() {
              for (let e3 in this.coords) if ("angle" === this.coords[e3].type) return true;
              return false;
            }
            getFormat(e3) {
              if (!e3) return null;
              "default" === e3 ? e3 = Object.values(this.formats)[0] : "string" == typeof e3 && (e3 = this.formats[e3]);
              let t3 = Mt.get(e3, this);
              return t3 !== e3 && e3.name in this.formats && (this.formats[e3.name] = t3), t3;
            }
            equals(e3) {
              return !!e3 && (this === e3 || this.id === e3 || this.id === e3.id);
            }
            to(e3, t3) {
              if (1 === arguments.length) {
                const r3 = Rt(e3);
                [e3, t3] = [r3.space, r3.coords];
              }
              if (e3 = _At.get(e3), this.equals(e3)) return t3;
              t3 = t3.map((e4) => it(e4) ? 0 : e4);
              let r2, n2, o2 = this.path, a2 = e3.path;
              for (let e4 = 0; e4 < o2.length && o2[e4].equals(a2[e4]); e4++) r2 = o2[e4], n2 = e4;
              if (!r2) throw new Error(`Cannot convert between color spaces ${this} and ${e3}: no connection space was found`);
              for (let e4 = o2.length - 1; e4 > n2; e4--) t3 = o2[e4].toBase(t3);
              for (let e4 = n2 + 1; e4 < a2.length; e4++) t3 = a2[e4].fromBase(t3);
              return t3;
            }
            from(e3, t3) {
              if (1 === arguments.length) {
                const r2 = Rt(e3);
                [e3, t3] = [r2.space, r2.coords];
              }
              return (e3 = _At.get(e3)).to(this, t3);
            }
            toString() {
              return `${this.name} (${this.id})`;
            }
            getMinCoords() {
              var _a3;
              let e3 = [];
              for (let t3 in this.coords) {
                let r2 = this.coords[t3], n2 = r2.range || r2.refRange;
                e3.push((_a3 = n2 == null ? void 0 : n2.min) != null ? _a3 : 0);
              }
              return e3;
            }
            static get all() {
              return [...new Set(Object.values(_At.registry))];
            }
            static register(e3, t3) {
              if (1 === arguments.length && (e3 = (t3 = arguments[0]).id), t3 = this.get(t3), this.registry[e3] && this.registry[e3] !== t3) throw new Error(`Duplicate color space registration: '${e3}'`);
              if (this.registry[e3] = t3, 1 === arguments.length && t3.aliases) for (let e4 of t3.aliases) this.register(e4, t3);
              return t3;
            }
            static get(e3, ...t3) {
              if (!e3 || bt(e3, this)) return e3;
              if ("string" === ot(e3)) {
                let t4 = _At.registry[e3.toLowerCase()];
                if (!t4) throw new TypeError(`No color space found with id = "${e3}"`);
                return t4;
              }
              if (t3.length) return _At.get(...t3);
              throw new TypeError(`${e3} is not a valid color space`);
            }
            static findFormat(e3, t3 = _At.all) {
              var _a3, _b2;
              if (!e3) return null;
              "string" == typeof e3 && (e3 = { name: e3 });
              for (let r2 of t3) for (let [t4, n2] of Object.entries(r2.formats)) {
                (_a3 = n2.name) != null ? _a3 : n2.name = t4, (_b2 = n2.type) != null ? _b2 : n2.type = "function";
                let o2 = !(e3.name && n2.name !== e3.name || e3.type && n2.type !== e3.type);
                if (e3.id) {
                  let t5 = n2.ids || [n2.id], r3 = Array.isArray(e3.id) ? e3.id : [e3.id];
                  o2 && (o2 = r3.some((e4) => t5.includes(e4)));
                }
                if (o2) {
                  let e4 = Mt.get(n2, r2);
                  return e4 !== n2 && (r2.formats[n2.name] = e4), e4;
                }
              }
              return null;
            }
            static resolveCoord(e3, t3) {
              var _a3;
              let r2, n2, o2 = ot(e3);
              if ("string" === o2 ? e3.includes(".") ? [r2, n2] = e3.split(".") : [r2, n2] = [, e3] : Array.isArray(e3) ? [r2, n2] = e3 : (r2 = e3.space, n2 = e3.coordId), r2 = _At.get(r2), r2 || (r2 = t3), !r2) throw new TypeError(`Cannot resolve coordinate reference ${e3}: No color space specified and relative references are not allowed here`);
              if (o2 = ot(n2), "number" === o2 || "string" === o2 && n2 >= 0) {
                let e4 = Object.entries(r2.coords)[n2];
                if (e4) return __spreadValues({ space: r2, id: e4[0], index: n2 }, e4[1]);
              }
              r2 = _At.get(r2);
              let a2 = n2.toLowerCase(), i2 = 0;
              for (let e4 in r2.coords) {
                let t4 = r2.coords[e4];
                if (e4.toLowerCase() === a2 || ((_a3 = t4.name) == null ? void 0 : _a3.toLowerCase()) === a2) return __spreadValues({ space: r2, id: e4, index: i2 }, t4);
                i2++;
              }
              throw new TypeError(`No "${n2}" coordinate found in ${r2.name}. Its coordinates are: ${Object.keys(r2.coords).join(", ")}`);
            }
          };
          __publicField(_At, "registry", {});
          __publicField(_At, "DEFAULT_FORMAT", { type: "functions", name: "color" });
          let At = _At;
          function Tt(e3) {
            let t3 = [e3];
            for (let r2 = e3; r2 = r2.base; ) t3.push(r2);
            return t3;
          }
          var Bt = new At({ id: "xyz-d65", name: "XYZ D65", coords: { x: { refRange: [0, 1], name: "X" }, y: { refRange: [0, 1], name: "Y" }, z: { refRange: [0, 1], name: "Z" } }, white: "D65", formats: { color: { ids: ["xyz-d65", "xyz"] } }, aliases: ["xyz"] });
          class Pt extends At {
            constructor(e3) {
              var _a3, _b2, _c2;
              e3.coords || (e3.coords = { r: { range: [0, 1], name: "Red" }, g: { range: [0, 1], name: "Green" }, b: { range: [0, 1], name: "Blue" } }), e3.base || (e3.base = Bt), e3.toXYZ_M && e3.fromXYZ_M && ((_a3 = e3.toBase) != null ? _a3 : e3.toBase = (t3) => {
                let r2 = rt(t3, e3.toXYZ_M);
                return this.white !== this.base.white && (r2 = Ct(this.white, this.base.white, r2)), r2;
              }, (_b2 = e3.fromBase) != null ? _b2 : e3.fromBase = (t3) => rt(t3 = Ct(this.base.white, this.white, t3), e3.fromXYZ_M)), (_c2 = e3.referred) != null ? _c2 : e3.referred = "display", super(e3);
            }
          }
          function Nt(e3, t3 = {}) {
            if (Array.isArray(e3)) return e3.map((e4) => Nt(e4, t3));
            let _a3 = t3, { cssProperty: r2 = "background-color", element: n2 } = _a3, o2 = __objRest(_a3, ["cssProperty", "element"]), a2 = null;
            try {
              return Rt(e3, o2);
            } catch (e4) {
              a2 = e4;
            }
            let { CSS: i2, getComputedStyle: s2 } = globalThis;
            if (nt(e3) && n2 && i2 && s2 && i2.supports(r2, e3)) {
              let t4 = n2.style[r2];
              e3 !== t4 && (n2.style[r2] = e3);
              let i3 = s2(n2).getPropertyValue(r2);
              if (e3 !== t4 && (n2.style[r2] = t4), i3 !== e3) try {
                return Rt(i3, o2);
              } catch (e4) {
                a2 = e4;
              }
              else a2 = { message: "Color value is a valid CSS color, but it could not be resolved :(" };
            }
            return t3.errorMeta && (t3.errorMeta.error = a2), null;
          }
          function Lt(e3, t3) {
            e3 = Rt(e3);
            let r2, n2 = At.get(t3, t3 == null ? void 0 : t3.space), o2 = t3 == null ? void 0 : t3.precision;
            return r2 = !n2 || e3.space.equals(n2) ? e3.coords.slice() : n2.from(e3), void 0 === o2 ? r2 : r2.map((e4) => lt(e4, o2));
          }
          function Dt(e3, t3) {
            var _a3;
            if (e3 = Rt(e3), "alpha" === t3) return (_a3 = e3.alpha) != null ? _a3 : 1;
            let { space: r2, index: n2 } = At.resolveCoord(t3, e3.space);
            return Lt(e3, r2)[n2];
          }
          function Ft(e3, t3, r2, n2) {
            return e3 = Rt(e3), Array.isArray(t3) && ([t3, r2, n2] = [e3.space, t3, r2]), t3 = At.get(t3), e3.coords = t3 === e3.space ? r2.slice() : t3.to(e3.space, r2), void 0 !== n2 && (e3.alpha = n2), e3;
          }
          function It(e3, t3, r2) {
            if (e3 = Rt(e3), 2 === arguments.length && "object" === ot(arguments[1])) {
              let t4 = arguments[1];
              for (let r3 in t4) It(e3, r3, t4[r3]);
            } else if ("function" == typeof r2 && (r2 = r2(Dt(e3, t3))), "alpha" === t3) e3.alpha = r2;
            else {
              let { space: n2, index: o2 } = At.resolveCoord(t3, e3.space), a2 = Lt(e3, n2);
              a2[o2] = r2, Ft(e3, n2, a2);
            }
            return e3;
          }
          Ft.returns = "color", It.returns = "color";
          var $t = new At({ id: "xyz-d50", name: "XYZ D50", white: "D50", base: Bt, fromBase: (e3) => Ct(Bt.white, "D50", e3), toBase: (e3) => Ct("D50", Bt.white, e3) });
          const zt = 216 / 24389, qt = 24 / 116, Ht = 24389 / 27;
          let Wt = St.D50;
          var Gt = new At({ id: "lab", name: "Lab", coords: { l: { refRange: [0, 100], name: "Lightness" }, a: { refRange: [-125, 125] }, b: { refRange: [-125, 125] } }, white: Wt, base: $t, fromBase(e3) {
            let t3 = e3.map((e4, t4) => e4 / Wt[t4]), r2 = t3.map((e4) => e4 > zt ? Math.cbrt(e4) : (Ht * e4 + 16) / 116);
            return [116 * r2[1] - 16, 500 * (r2[0] - r2[1]), 200 * (r2[1] - r2[2])];
          }, toBase(e3) {
            let [t3, r2, n2] = e3, o2 = [];
            return o2[1] = (t3 + 16) / 116, o2[0] = r2 / 500 + o2[1], o2[2] = o2[1] - n2 / 200, [o2[0] > qt ? Math.pow(o2[0], 3) : (116 * o2[0] - 16) / Ht, e3[0] > 8 ? Math.pow((e3[0] + 16) / 116, 3) : e3[0] / Ht, o2[2] > qt ? Math.pow(o2[2], 3) : (116 * o2[2] - 16) / Ht].map((e4, t4) => e4 * Wt[t4]);
          }, formats: { lab: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <percentage>"] } } });
          function Yt(e3) {
            return "number" != typeof e3 ? e3 : (e3 % 360 + 360) % 360;
          }
          function Ut(e3, t3) {
            let [r2, n2] = t3, o2 = it(r2), a2 = it(n2);
            if (o2 && a2) return [r2, n2];
            if (o2 ? r2 = n2 : a2 && (n2 = r2), "raw" === e3) return t3;
            r2 = Yt(r2), n2 = Yt(n2);
            let i2 = n2 - r2;
            return "increasing" === e3 ? i2 < 0 && (n2 += 360) : "decreasing" === e3 ? i2 > 0 && (r2 += 360) : "longer" === e3 ? -180 < i2 && i2 < 180 && (i2 > 0 ? r2 += 360 : n2 += 360) : "shorter" === e3 && (i2 > 180 ? r2 += 360 : i2 < -180 && (n2 += 360)), [r2, n2];
          }
          var Vt = new At({ id: "lch", name: "LCH", coords: { l: { refRange: [0, 100], name: "Lightness" }, c: { refRange: [0, 150], name: "Chroma" }, h: { refRange: [0, 360], type: "angle", name: "Hue" } }, base: Gt, fromBase(e3) {
            if (void 0 === this.\u03B5) {
              let e4 = Object.values(this.base.coords)[1].refRange, t4 = e4[1] - e4[0];
              this.\u03B5 = t4 / 1e5;
            }
            let [t3, r2, n2] = e3, o2 = Math.abs(r2) < this.\u03B5 && Math.abs(n2) < this.\u03B5, a2 = o2 ? null : Yt(180 * Math.atan2(n2, r2) / Math.PI);
            return [t3, o2 ? 0 : Math.sqrt(r2 ** 2 + n2 ** 2), a2];
          }, toBase(e3) {
            let [t3, r2, n2] = e3, o2 = null, a2 = null;
            return it(n2) || (r2 = r2 < 0 ? 0 : r2, o2 = r2 * Math.cos(n2 * Math.PI / 180), a2 = r2 * Math.sin(n2 * Math.PI / 180)), [t3, o2, a2];
          }, formats: { lch: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <angle>"] } } });
          const Jt = 25 ** 7, Xt = Math.PI, Kt = 180 / Xt, Zt = Xt / 180;
          function Qt(e3) {
            const t3 = e3 * e3;
            return t3 * t3 * t3 * e3;
          }
          function er(e3, t3, { kL: r2 = 1, kC: n2 = 1, kH: o2 = 1 } = {}) {
            [e3, t3] = Rt([e3, t3]);
            let [a2, i2, s2] = Gt.from(e3), l2 = Vt.from(Gt, [a2, i2, s2])[1], [c2, u2, h2] = Gt.from(t3), f2 = Vt.from(Gt, [c2, u2, h2])[1];
            l2 < 0 && (l2 = 0), f2 < 0 && (f2 = 0);
            let p2 = Qt((l2 + f2) / 2), d2 = 0.5 * (1 - Math.sqrt(p2 / (p2 + Jt))), g2 = (1 + d2) * i2, m2 = (1 + d2) * u2, b2 = Math.sqrt(g2 ** 2 + s2 ** 2), y2 = Math.sqrt(m2 ** 2 + h2 ** 2), w2 = 0 === g2 && 0 === s2 ? 0 : Math.atan2(s2, g2), v2 = 0 === m2 && 0 === h2 ? 0 : Math.atan2(h2, m2);
            w2 < 0 && (w2 += 2 * Xt), v2 < 0 && (v2 += 2 * Xt), w2 *= Kt, v2 *= Kt;
            let k2, _2 = c2 - a2, M2 = y2 - b2, S2 = v2 - w2, E2 = w2 + v2, C2 = Math.abs(S2);
            b2 * y2 === 0 ? k2 = 0 : C2 <= 180 ? k2 = S2 : S2 > 180 ? k2 = S2 - 360 : S2 < -180 ? k2 = S2 + 360 : vt.warn("the unthinkable has happened");
            let x2, O2 = 2 * Math.sqrt(y2 * b2) * Math.sin(k2 * Zt / 2), j2 = (a2 + c2) / 2, R2 = (b2 + y2) / 2, A2 = Qt(R2);
            x2 = b2 * y2 === 0 ? E2 : C2 <= 180 ? E2 / 2 : E2 < 360 ? (E2 + 360) / 2 : (E2 - 360) / 2;
            let T2 = (j2 - 50) ** 2, B2 = 1 + 0.015 * T2 / Math.sqrt(20 + T2), P2 = 1 + 0.045 * R2, N2 = 1;
            N2 -= 0.17 * Math.cos((x2 - 30) * Zt), N2 += 0.24 * Math.cos(2 * x2 * Zt), N2 += 0.32 * Math.cos((3 * x2 + 6) * Zt), N2 -= 0.2 * Math.cos((4 * x2 - 63) * Zt);
            let L2 = 1 + 0.015 * R2 * N2, D2 = 30 * Math.exp(-1 * ((x2 - 275) / 25) ** 2), F2 = 2 * Math.sqrt(A2 / (A2 + Jt)), I2 = (_2 / (r2 * B2)) ** 2;
            return I2 += (M2 / (n2 * P2)) ** 2, I2 += (O2 / (o2 * L2)) ** 2, I2 += -1 * Math.sin(2 * D2 * Zt) * F2 * (M2 / (n2 * P2)) * (O2 / (o2 * L2)), Math.sqrt(I2);
          }
          const tr = [[0.819022437996703, 0.3619062600528904, -0.1288737815209879], [0.0329836539323885, 0.9292868615863434, 0.0361446663506424], [0.0481771893596242, 0.2642395317527308, 0.6335478284694309]], rr = [[1.2268798758459243, -0.5578149944602171, 0.2813910456659647], [-0.0405757452148008, 1.112286803280317, -0.0717110580655164], [-0.0763729366746601, -0.4214933324022432, 1.5869240198367816]], nr = [[0.210454268309314, 0.7936177747023054, -0.0040720430116193], [1.9779985324311684, -2.42859224204858, 0.450593709617411], [0.0259040424655478, 0.7827717124575296, -0.8086757549230774]], or = [[1, 0.3963377773761749, 0.2158037573099136], [1, -0.1055613458156586, -0.0638541728258133], [1, -0.0894841775298119, -1.2914855480194092]];
          var ar = new At({ id: "oklab", name: "Oklab", coords: { l: { refRange: [0, 1], name: "Lightness" }, a: { refRange: [-0.4, 0.4] }, b: { refRange: [-0.4, 0.4] } }, white: "D65", base: Bt, fromBase(e3) {
            let t3 = rt(e3, tr);
            return t3[0] = Math.cbrt(t3[0]), t3[1] = Math.cbrt(t3[1]), t3[2] = Math.cbrt(t3[2]), rt(t3, nr, t3);
          }, toBase(e3) {
            let t3 = rt(e3, or);
            return t3[0] = t3[0] ** 3, t3[1] = t3[1] ** 3, t3[2] = t3[2] ** 3, rt(t3, rr, t3);
          }, formats: { oklab: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <percentage>"] } } });
          function ir(e3, t3) {
            [e3, t3] = Rt([e3, t3]);
            let [r2, n2, o2] = ar.from(e3), [a2, i2, s2] = ar.from(t3), l2 = r2 - a2, c2 = n2 - i2, u2 = o2 - s2;
            return Math.sqrt(l2 ** 2 + c2 ** 2 + u2 ** 2);
          }
          function sr(e3, t3, { epsilon: r2 = 75e-6 } = {}) {
            e3 = Rt(e3), t3 || (t3 = e3.space), t3 = At.get(t3);
            let n2 = e3.coords;
            return t3 !== e3.space && (n2 = t3.from(e3)), t3.inGamut(n2, { epsilon: r2 });
          }
          function lr(e3) {
            return { space: e3.space, coords: e3.coords.slice(), alpha: e3.alpha };
          }
          function cr(e3, t3, r2 = "lab") {
            let n2 = (r2 = At.get(r2)).from(e3), o2 = r2.from(t3);
            return Math.sqrt(n2.reduce((e4, t4, r3) => {
              let n3 = o2[r3];
              return it(t4) || it(n3) ? e4 : e4 + (n3 - t4) ** 2;
            }, 0));
          }
          const ur = Math.PI / 180;
          var hr = new At({ id: "xyz-abs-d65", cssId: "--xyz-abs-d65", name: "Absolute XYZ D65", coords: { x: { refRange: [0, 9504.7], name: "Xa" }, y: { refRange: [0, 1e4], name: "Ya" }, z: { refRange: [0, 10888.3], name: "Za" } }, base: Bt, fromBase: (e3) => e3.map((e4) => 203 * e4), toBase: (e3) => e3.map((e4) => e4 / 203) });
          const fr = 1.15, pr = 0.66, dr = 2610 / 16384, gr = 16384 / 2610, mr = 0.8359375, br = 2413 / 128, yr = 18.6875, wr = 1.7 * 2523 / 32, vr = 32 / (1.7 * 2523), kr = -0.56, _r = 16295499532821565e-27, Mr = [[0.41478972, 0.579999, 0.014648], [-0.20151, 1.120649, 0.0531008], [-0.0166008, 0.2648, 0.6684799]], Sr = [[1.9242264357876067, -1.0047923125953657, 0.037651404030618], [0.35031676209499907, 0.7264811939316552, -0.06538442294808501], [-0.09098281098284752, -0.3127282905230739, 1.5227665613052603]], Er = [[0.5, 0.5, 0], [3.524, -4.066708, 0.542708], [0.199076, 1.096799, -1.295875]], Cr = [[1, 0.13860504327153927, 0.05804731615611883], [1, -0.1386050432715393, -0.058047316156118904], [1, -0.09601924202631895, -0.811891896056039]];
          var xr = new At({ id: "jzazbz", name: "Jzazbz", coords: { jz: { refRange: [0, 1], name: "Jz" }, az: { refRange: [-0.21, 0.21] }, bz: { refRange: [-0.21, 0.21] } }, base: hr, fromBase(e3) {
            let [t3, r2, n2] = e3, o2 = rt([fr * t3 - (fr - 1) * n2, pr * r2 - (pr - 1) * t3, n2], Mr).map(function(e4) {
              let t4 = mr + br * dt(e4 / 1e4, dr), r3 = 1 + yr * dt(e4 / 1e4, dr);
              return dt(t4 / r3, wr);
            }), [a2, i2, s2] = rt(o2, Er);
            return [(1 + kr) * a2 / (1 + kr * a2) - _r, i2, s2];
          }, toBase(e3) {
            let [t3, r2, n2] = e3, o2 = rt([(t3 + _r) / (1 + kr - kr * (t3 + _r)), r2, n2], Cr).map(function(e4) {
              let t4 = mr - dt(e4, vr), r3 = yr * dt(e4, vr) - br;
              return 1e4 * dt(t4 / r3, gr);
            }), [a2, i2, s2] = rt(o2, Sr), l2 = (a2 + (fr - 1) * s2) / fr;
            return [l2, (i2 + (pr - 1) * l2) / pr, s2];
          }, formats: { jzazbz: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <percentage>"] } } }), Or = new At({ id: "jzczhz", name: "JzCzHz", coords: { jz: { refRange: [0, 1], name: "Jz" }, cz: { refRange: [0, 0.26], name: "Chroma" }, hz: { refRange: [0, 360], type: "angle", name: "Hue" } }, base: xr, fromBase: Vt.fromBase, toBase: Vt.toBase, formats: { jzczhz: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <angle>"] } } });
          const jr = 0.8359375, Rr = 2413 / 128, Ar = 18.6875, Tr = 2610 / 16384, Br = 16384 / 2610, Pr = 32 / 2523, Nr = [[0.3592832590121217, 0.6976051147779502, -0.035891593232029], [-0.1920808463704993, 1.100476797037432, 0.0753748658519118], [0.0070797844607479, 0.0748396662186362, 0.8433265453898765]], Lr = [[0.5, 0.5, 0], [6610 / 4096, -13613 / 4096, 7003 / 4096], [17933 / 4096, -17390 / 4096, -543 / 4096]], Dr = [[0.9999999999999998, 0.0086090370379328, 0.111029625003026], [0.9999999999999998, -0.0086090370379328, -0.1110296250030259], [0.9999999999999998, 0.5600313357106791, -0.3206271749873188]], Fr = [[2.0701522183894223, -1.3263473389671563, 0.2066510476294053], [0.3647385209748072, 0.6805660249472273, -0.0453045459220347], [-0.0497472075358123, -0.0492609666966131, 1.1880659249923042]];
          var Ir = new At({ id: "ictcp", name: "ICTCP", coords: { i: { refRange: [0, 1], name: "I" }, ct: { refRange: [-0.5, 0.5], name: "CT" }, cp: { refRange: [-0.5, 0.5], name: "CP" } }, base: hr, fromBase: (e3) => {
            return t3 = rt(e3, Nr), rt(t3.map(function(e4) {
              return ((jr + Rr * (e4 / 1e4) ** Tr) / (1 + Ar * (e4 / 1e4) ** Tr)) ** 78.84375;
            }), Lr);
            var t3;
          }, toBase(e3) {
            let t3 = function(e4) {
              return rt(e4, Dr).map(function(e5) {
                return 1e4 * (Math.max(e5 ** Pr - jr, 0) / (Rr - Ar * e5 ** Pr)) ** Br;
              });
            }(e3);
            return rt(t3, Fr);
          }, formats: { ictcp: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <percentage>"] } } });
          const $r = St.D65, zr = 1 / 0.42, qr = 2 * Math.PI, Hr = [[0.401288, 0.650173, -0.051461], [-0.250268, 1.204414, 0.045854], [-2079e-6, 0.048952, 0.953127]], Wr = [[1.8620678550872327, -1.0112546305316843, 0.14918677544445175], [0.38752654323613717, 0.6214474419314753, -0.008973985167612518], [-0.015841498849333856, -0.03412293802851557, 1.0499644368778496]], Gr = [[460, 451, 288], [460, -891, -261], [460, -220, -6300]], Yr = { dark: [0.8, 0.525, 0.8], dim: [0.9, 0.59, 0.9], average: [1, 0.69, 1] }, Ur = { h: [20.14, 90, 164.25, 237.53, 380.14], e: [0.8, 0.7, 1, 1.2, 0.8], H: [0, 100, 200, 300, 400] }, Vr = 180 / Math.PI, Jr = Math.PI / 180;
          function Xr(e3, t3) {
            const r2 = e3.map((e4) => {
              const r3 = dt(t3 * Math.abs(e4) * 0.01, 0.42);
              return 400 * pt(r3, e4) / (r3 + 27.13);
            });
            return r2;
          }
          function Kr(e3, t3, r2, n2, o2) {
            const a2 = {};
            a2.discounting = o2, a2.refWhite = e3, a2.surround = n2;
            const i2 = e3.map((e4) => 100 * e4);
            a2.la = t3, a2.yb = r2;
            const s2 = i2[1], l2 = rt(i2, Hr);
            let c2 = Yr[a2.surround];
            const u2 = c2[0];
            a2.c = c2[1], a2.nc = c2[2];
            const h2 = (1 / (5 * a2.la + 1)) ** 4;
            a2.fl = h2 * a2.la + 0.1 * (1 - h2) * (1 - h2) * Math.cbrt(5 * a2.la), a2.flRoot = a2.fl ** 0.25, a2.n = a2.yb / s2, a2.z = 1.48 + Math.sqrt(a2.n), a2.nbb = 0.725 * a2.n ** -0.2, a2.ncb = a2.nbb;
            const f2 = Math.max(Math.min(u2 * (1 - 1 / 3.6 * Math.exp((-a2.la - 42) / 92)), 1), 0);
            a2.dRgb = l2.map((e4) => ct(1, s2 / e4, f2)), a2.dRgbInv = a2.dRgb.map((e4) => 1 / e4);
            const p2 = l2.map((e4, t4) => e4 * a2.dRgb[t4]), d2 = Xr(p2, a2.fl);
            return a2.aW = a2.nbb * (2 * d2[0] + d2[1] + 0.05 * d2[2]), a2;
          }
          const Zr = Kr($r, 64 / Math.PI * 0.2, 20, "average", false);
          function Qr(e3, t3) {
            if (!(void 0 !== e3.J ^ void 0 !== e3.Q)) throw new Error("Conversion requires one and only one: 'J' or 'Q'");
            if (!(void 0 !== e3.C ^ void 0 !== e3.M ^ void 0 !== e3.s)) throw new Error("Conversion requires one and only one: 'C', 'M' or 's'");
            if (!(void 0 !== e3.h ^ void 0 !== e3.H)) throw new Error("Conversion requires one and only one: 'h' or 'H'");
            if (0 === e3.J || 0 === e3.Q) return [0, 0, 0];
            let r2 = 0;
            r2 = void 0 !== e3.h ? Yt(e3.h) * Jr : function(e4) {
              let t4 = (e4 % 400 + 400) % 400;
              const r3 = Math.floor(0.01 * t4);
              t4 %= 100;
              const [n3, o3] = Ur.h.slice(r3, r3 + 2), [a3, i3] = Ur.e.slice(r3, r3 + 2);
              return Yt((t4 * (i3 * n3 - a3 * o3) - 100 * n3 * i3) / (t4 * (i3 - a3) - 100 * i3));
            }(e3.H) * Jr;
            const n2 = Math.cos(r2), o2 = Math.sin(r2);
            let a2 = 0;
            void 0 !== e3.J ? a2 = 0.1 * dt(e3.J, 0.5) : void 0 !== e3.Q && (a2 = 0.25 * t3.c * e3.Q / ((t3.aW + 4) * t3.flRoot));
            let i2 = 0;
            void 0 !== e3.C ? i2 = e3.C / a2 : void 0 !== e3.M ? i2 = e3.M / t3.flRoot / a2 : void 0 !== e3.s && (i2 = 4e-4 * e3.s ** 2 * (t3.aW + 4) / t3.c);
            const s2 = dt(i2 * Math.pow(1.64 - Math.pow(0.29, t3.n), -0.73), 10 / 9), l2 = 0.25 * (Math.cos(r2 + 2) + 3.8), c2 = t3.aW * dt(a2, 2 / t3.c / t3.z), u2 = 5e4 / 13 * t3.nc * t3.ncb * l2, h2 = c2 / t3.nbb, f2 = 23 * (h2 + 0.305) * gt(s2, 23 * u2 + s2 * (11 * n2 + 108 * o2)), p2 = function(e4, t4) {
              const r3 = 100 / t4 * 2588.068098016295;
              return e4.map((e5) => {
                const t5 = Math.abs(e5);
                return pt(r3 * dt(t5 / (400 - t5), zr), e5);
              });
            }(rt([h2, f2 * n2, f2 * o2], Gr).map((e4) => 1 * e4 / 1403), t3.fl);
            return rt(p2.map((e4, r3) => e4 * t3.dRgbInv[r3]), Wr).map((e4) => e4 / 100);
          }
          function en(e3, t3) {
            const r2 = e3.map((e4) => 100 * e4), n2 = Xr(rt(r2, Hr).map((e4, r3) => e4 * t3.dRgb[r3]), t3.fl), o2 = n2[0] + (-12 * n2[1] + n2[2]) / 11, a2 = (n2[0] + n2[1] - 2 * n2[2]) / 9, i2 = (Math.atan2(a2, o2) % qr + qr) % qr, s2 = 0.25 * (Math.cos(i2 + 2) + 3.8), l2 = dt(5e4 / 13 * t3.nc * t3.ncb * gt(s2 * Math.sqrt(o2 ** 2 + a2 ** 2), n2[0] + n2[1] + 1.05 * n2[2] + 0.305), 0.9) * Math.pow(1.64 - Math.pow(0.29, t3.n), 0.73), c2 = dt(t3.nbb * (2 * n2[0] + n2[1] + 0.05 * n2[2]) / t3.aW, 0.5 * t3.c * t3.z), u2 = 100 * dt(c2, 2), h2 = 4 / t3.c * c2 * (t3.aW + 4) * t3.flRoot, f2 = l2 * c2, p2 = f2 * t3.flRoot, d2 = Yt(i2 * Vr), g2 = function(e4) {
              let t4 = Yt(e4);
              t4 <= Ur.h[0] && (t4 += 360);
              const r3 = mt(Ur.h, t4) - 1, [n3, o3] = Ur.h.slice(r3, r3 + 2), [a3, i3] = Ur.e.slice(r3, r3 + 2), s3 = (t4 - n3) / a3;
              return Ur.H[r3] + 100 * s3 / (s3 + (o3 - t4) / i3);
            }(d2);
            return { J: u2, C: f2, h: d2, s: 50 * dt(t3.c * l2 / (t3.aW + 4), 0.5), Q: h2, M: p2, H: g2 };
          }
          var tn = new At({ id: "cam16-jmh", cssId: "--cam16-jmh", name: "CAM16-JMh", coords: { j: { refRange: [0, 100], name: "J" }, m: { refRange: [0, 105], name: "Colorfulness" }, h: { refRange: [0, 360], type: "angle", name: "Hue" } }, base: Bt, fromBase(e3) {
            void 0 === this.\u03B5 && (this.\u03B5 = Object.values(this.coords)[1].refRange[1] / 1e5);
            const t3 = en(e3, Zr), r2 = Math.abs(t3.M) < this.\u03B5;
            return [t3.J, r2 ? 0 : t3.M, r2 ? null : t3.h];
          }, toBase: (e3) => Qr({ J: e3[0], M: e3[1], h: e3[2] }, Zr) });
          const rn = St.D65, nn = 216 / 24389, on = 24389 / 27;
          function an(e3) {
            return e3 > 8 ? Math.pow((e3 + 16) / 116, 3) : e3 / on;
          }
          const sn = Kr(rn, 200 / Math.PI * an(50), 100 * an(50), "average", false);
          var ln = new At({ id: "hct", name: "HCT", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, c: { refRange: [0, 145], name: "Colorfulness" }, t: { refRange: [0, 100], name: "Tone" } }, base: Bt, fromBase(e3) {
            void 0 === this.\u03B5 && (this.\u03B5 = Object.values(this.coords)[1].refRange[1] / 1e5);
            let t3 = function(e4) {
              const t4 = function(e5) {
                return 116 * (e5 > nn ? Math.cbrt(e5) : (on * e5 + 16) / 116) - 16;
              }(e4[1]);
              if (0 === t4) return [0, 0, 0];
              const r2 = en(e4, sn);
              return [Yt(r2.h), r2.C, t4];
            }(e3);
            return t3[1] < this.\u03B5 && (t3[1] = 0, t3[0] = null), t3;
          }, toBase: (e3) => function(e4, t3) {
            let [r2, n2, o2] = e4, a2 = [], i2 = 0;
            if (0 === o2) return [0, 0, 0];
            let s2 = an(o2);
            i2 = o2 > 0 ? 0.00379058511492914 * o2 ** 2 + 0.608983189401032 * o2 + 0.9155088574762233 : 9514440756550361e-21 * o2 ** 2 + 0.08693057439788597 * o2 - 21.928975842194614;
            let l2 = 0, c2 = 1 / 0;
            for (; l2 <= 15; ) {
              a2 = Qr({ J: i2, C: n2, h: r2 }, t3);
              const e5 = Math.abs(a2[1] - s2);
              if (e5 < c2) {
                if (e5 <= 2e-12) return a2;
                c2 = e5;
              }
              i2 -= (a2[1] - s2) * i2 / (2 * a2[1]), l2 += 1;
            }
            return Qr({ J: i2, C: n2, h: r2 }, t3);
          }(e3, sn), formats: { color: { id: "--hct", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } });
          const cn = Math.PI / 180, un = [1, 7e-3, 0.0228];
          function hn(e3) {
            e3[1] < 0 && (e3 = ln.fromBase(ln.toBase(e3)));
            const t3 = Math.log(Math.max(1 + un[2] * e3[1] * sn.flRoot, 1)) / un[2], r2 = e3[0] * cn, n2 = t3 * Math.cos(r2), o2 = t3 * Math.sin(r2);
            return [e3[2], n2, o2];
          }
          var fn = { deltaE76: function(e3, t3) {
            return cr(e3, t3, "lab");
          }, deltaECMC: function(e3, t3, { l: r2 = 2, c: n2 = 1 } = {}) {
            [e3, t3] = Rt([e3, t3]);
            let [o2, a2, i2] = Gt.from(e3), [, s2, l2] = Vt.from(Gt, [o2, a2, i2]), [c2, u2, h2] = Gt.from(t3), f2 = Vt.from(Gt, [c2, u2, h2])[1];
            s2 < 0 && (s2 = 0), f2 < 0 && (f2 = 0);
            let p2 = o2 - c2, d2 = s2 - f2, g2 = (a2 - u2) ** 2 + (i2 - h2) ** 2 - d2 ** 2, m2 = 0.511;
            o2 >= 16 && (m2 = 0.040975 * o2 / (1 + 0.01765 * o2));
            let b2, y2 = 0.0638 * s2 / (1 + 0.0131 * s2) + 0.638;
            it(l2) && (l2 = 0), b2 = l2 >= 164 && l2 <= 345 ? 0.56 + Math.abs(0.2 * Math.cos((l2 + 168) * ur)) : 0.36 + Math.abs(0.4 * Math.cos((l2 + 35) * ur));
            let w2 = Math.pow(s2, 4), v2 = Math.sqrt(w2 / (w2 + 1900)), k2 = (p2 / (r2 * m2)) ** 2;
            return k2 += (d2 / (n2 * y2)) ** 2, k2 += g2 / (y2 * (v2 * b2 + 1 - v2)) ** 2, Math.sqrt(k2);
          }, deltaE2000: er, deltaEJz: function(e3, t3) {
            [e3, t3] = Rt([e3, t3]);
            let [r2, n2, o2] = Or.from(e3), [a2, i2, s2] = Or.from(t3), l2 = r2 - a2, c2 = n2 - i2;
            it(o2) && it(s2) ? (o2 = 0, s2 = 0) : it(o2) ? o2 = s2 : it(s2) && (s2 = o2);
            let u2 = o2 - s2, h2 = 2 * Math.sqrt(n2 * i2) * Math.sin(u2 / 2 * (Math.PI / 180));
            return Math.sqrt(l2 ** 2 + c2 ** 2 + h2 ** 2);
          }, deltaEITP: function(e3, t3) {
            [e3, t3] = Rt([e3, t3]);
            let [r2, n2, o2] = Ir.from(e3), [a2, i2, s2] = Ir.from(t3);
            return 720 * Math.sqrt((r2 - a2) ** 2 + 0.25 * (n2 - i2) ** 2 + (o2 - s2) ** 2);
          }, deltaEOK: ir, deltaEOK2: function(e3, t3) {
            [e3, t3] = Rt([e3, t3]);
            let [r2, n2, o2] = ar.from(e3), [a2, i2, s2] = ar.from(t3), l2 = r2 - a2, c2 = 2 * (n2 - i2), u2 = 2 * (o2 - s2);
            return Math.sqrt(l2 ** 2 + c2 ** 2 + u2 ** 2);
          }, deltaEHCT: function(e3, t3) {
            [e3, t3] = Rt([e3, t3]);
            let [r2, n2, o2] = hn(ln.from(e3)), [a2, i2, s2] = hn(ln.from(t3));
            return Math.sqrt((r2 - a2) ** 2 + (n2 - i2) ** 2 + (o2 - s2) ** 2);
          } };
          const pn = { hct: { method: "hct.c", jnd: 2, deltaEMethod: "hct", blackWhiteClamp: {} }, "hct-tonal": { method: "hct.c", jnd: 0, deltaEMethod: "hct", blackWhiteClamp: { channel: "hct.t", min: 0, max: 100 } } };
          function dn(e3, { method: t3 = vt.gamut_mapping, space: r2, deltaEMethod: n2 = "", jnd: o2 = 2, blackWhiteClamp: a2 } = {}) {
            if (e3 = Rt(e3), nt(arguments[1]) ? r2 = arguments[1] : r2 || (r2 = e3.space), sr(e3, r2 = At.get(r2), { epsilon: 0 })) return e3;
            let i2;
            if ("css" === t3) i2 = function(e4, { space: t4 } = {}) {
              const r3 = 0.02, n3 = 1e-4;
              e4 = Rt(e4), t4 || (t4 = e4.space), t4 = At.get(t4);
              const o3 = At.get("oklch");
              if (t4.isUnbounded) return mn(e4, t4);
              const a3 = mn(e4, o3);
              let i3 = a3.coords[0];
              if (i3 >= 1) {
                const r4 = mn(gn.WHITE, t4);
                return r4.alpha = e4.alpha, mn(r4, t4);
              }
              if (i3 <= 0) {
                const r4 = mn(gn.BLACK, t4);
                return r4.alpha = e4.alpha, mn(r4, t4);
              }
              if (sr(a3, t4, { epsilon: 0 })) return mn(a3, t4);
              function s2(e5) {
                const r4 = mn(e5, t4), n4 = Object.values(t4.coords);
                return r4.coords = r4.coords.map((e6, t5) => {
                  if ("range" in n4[t5]) {
                    const [r5, o4] = n4[t5].range;
                    return ft(r5, e6, o4);
                  }
                  return e6;
                }), r4;
              }
              let l2 = 0, c2 = a3.coords[1], u2 = true, h2 = lr(a3), f2 = s2(h2), p2 = ir(f2, h2);
              if (p2 < r3) return f2;
              for (; c2 - l2 > n3; ) {
                const e5 = (l2 + c2) / 2;
                if (h2.coords[1] = e5, u2 && sr(h2, t4, { epsilon: 0 })) l2 = e5;
                else if (f2 = s2(h2), p2 = ir(f2, h2), p2 < r3) {
                  if (r3 - p2 < n3) break;
                  u2 = false, l2 = e5;
                } else c2 = e5;
              }
              return f2;
            }(e3, { space: r2 });
            else {
              if ("clip" === t3 || sr(e3, r2)) i2 = mn(e3, r2);
              else {
                Object.prototype.hasOwnProperty.call(pn, t3) && ({ method: t3, jnd: o2, deltaEMethod: n2, blackWhiteClamp: a2 } = pn[t3]);
                let s2 = er;
                if ("" !== n2) {
                  for (let e4 in fn) if ("deltae" + n2.toLowerCase() === e4.toLowerCase()) {
                    s2 = fn[e4];
                    break;
                  }
                }
                0 === o2 && (o2 = 1e-16);
                let l2 = dn(mn(e3, r2), { method: "clip", space: r2 });
                if (s2(e3, l2) > o2) {
                  if (a2 && 3 === Object.keys(a2).length) {
                    let t4 = At.resolveCoord(a2.channel), r3 = Dt(mn(e3, t4.space), t4.id);
                    if (it(r3) && (r3 = 0), r3 >= a2.max) return mn({ space: "xyz-d65", coords: St.D65 }, e3.space);
                    if (r3 <= a2.min) return mn({ space: "xyz-d65", coords: [0, 0, 0] }, e3.space);
                  }
                  let n3 = At.resolveCoord(t3), l3 = n3.space, c2 = n3.id, u2 = mn(e3, l3);
                  u2.coords.forEach((e4, t4) => {
                    it(e4) && (u2.coords[t4] = 0);
                  });
                  let h2 = (n3.range || n3.refRange)[0], f2 = function(e4) {
                    const t4 = e4 ? Math.floor(Math.log10(Math.abs(e4))) : 0;
                    return Math.max(parseFloat("1e" + (t4 - 2)), 1e-6);
                  }(o2), p2 = h2, d2 = Dt(u2, c2);
                  for (; d2 - p2 > f2; ) {
                    let e4 = lr(u2);
                    e4 = dn(e4, { space: r2, method: "clip" }), s2(u2, e4) - o2 < f2 ? p2 = Dt(u2, c2) : d2 = Dt(u2, c2), It(u2, c2, (p2 + d2) / 2);
                  }
                  i2 = mn(u2, r2);
                } else i2 = l2;
              }
              if ("clip" === t3 || !sr(i2, r2, { epsilon: 0 })) {
                let e4 = Object.values(r2.coords).map((e5) => e5.range || []);
                i2.coords = i2.coords.map((t4, r3) => {
                  let [n3, o3] = e4[r3];
                  return void 0 !== n3 && (t4 = Math.max(n3, t4)), void 0 !== o3 && (t4 = Math.min(t4, o3)), t4;
                });
              }
            }
            return r2 !== e3.space && (i2 = mn(i2, e3.space)), e3.coords = i2.coords, e3;
          }
          dn.returns = "color";
          const gn = { WHITE: { space: ar, coords: [1, 0, 0], alpha: 1 }, BLACK: { space: ar, coords: [0, 0, 0], alpha: 1 } };
          function mn(e3, t3, { inGamut: r2 } = {}) {
            e3 = Rt(e3);
            let n2 = (t3 = At.get(t3)).from(e3), o2 = { space: t3, coords: n2, alpha: e3.alpha };
            return r2 && (o2 = dn(o2, true === r2 ? void 0 : r2)), o2;
          }
          function bn(e3, t3 = {}) {
            var _a3, _b2, _c2, _d2;
            let r2, { precision: n2 = vt.precision, format: o2, inGamut: a2 = true, coords: i2, alpha: s2, commas: l2 } = t3, c2 = Rt(e3), u2 = o2, h2 = c2.parseMeta;
            h2 && !o2 && (h2.format.canSerialize() && (o2 = h2.format, u2 = h2.formatId), i2 != null ? i2 : i2 = h2.types, s2 != null ? s2 : s2 = h2.alphaType, l2 != null ? l2 : l2 = h2.commas), u2 && (o2 = (_a3 = c2.space.getFormat(o2)) != null ? _a3 : At.findFormat(u2)), o2 || (o2 = (_b2 = c2.space.getFormat("default")) != null ? _b2 : At.DEFAULT_FORMAT, u2 = o2.name), o2 && o2.space && o2.space !== c2.space && (c2 = mn(c2, o2.space));
            let f2 = c2.coords.slice();
            if (a2 || (a2 = o2.toGamut), a2 && !sr(c2) && (f2 = dn(lr(c2), true === a2 ? void 0 : a2).coords), "custom" === o2.type) {
              if (!o2.serialize) throw new TypeError(`format ${u2} can only be used to parse colors, not for serialization`);
              r2 = o2.serialize(f2, c2.alpha, t3);
            } else {
              let e4 = o2.name || "color", t4 = o2.serializeCoords(f2, n2, i2);
              if ("color" === e4) {
                let e5 = o2.id || ((_c2 = o2.ids) == null ? void 0 : _c2[0]) || c2.space.cssId || c2.space.id;
                t4.unshift(e5);
              }
              let a3 = c2.alpha;
              void 0 !== s2 && "object" != typeof s2 && (s2 = "string" == typeof s2 ? { type: s2 } : { include: s2 });
              let u3 = (_d2 = s2 == null ? void 0 : s2.type) != null ? _d2 : "<number>", h3 = true === (s2 == null ? void 0 : s2.include) || true === o2.alpha || false !== (s2 == null ? void 0 : s2.include) && false !== o2.alpha && a3 < 1, p2 = "";
              if (l2 != null ? l2 : l2 = o2.commas, h3) {
                if (null !== n2) {
                  let e5;
                  "<percentage>" === u3 && (e5 = "%", a3 *= 100), a3 = at(a3, { precision: n2, unit: e5 });
                }
                p2 = `${l2 ? "," : " /"} ${a3}`;
              }
              r2 = `${e4}(${t4.join(l2 ? ", " : " ")}${p2})`;
            }
            return r2;
          }
          mn.returns = "color";
          var yn = new Pt({ id: "rec2020-linear", cssId: "--rec2020-linear", name: "Linear REC.2020", white: "D65", toXYZ_M: [[0.6369580483012914, 0.14461690358620832, 0.1688809751641721], [0.2627002120112671, 0.6779980715188708, 0.05930171646986196], [0, 0.028072693049087428, 1.060985057710791]], fromXYZ_M: [[1.716651187971268, -0.355670783776392, -0.25336628137366], [-0.666684351832489, 1.616481236634939, 0.0157685458139111], [0.017639857445311, -0.042770613257809, 0.942103121235474]] }), wn = new Pt({ id: "rec2020", name: "REC.2020", base: yn, toBase: (e3) => e3.map(function(e4) {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return t3 * Math.pow(r2, 2.4);
          }), fromBase: (e3) => e3.map(function(e4) {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return t3 * Math.pow(r2, 1 / 2.4);
          }) }), vn = new Pt({ id: "p3-linear", cssId: "display-p3-linear", name: "Linear P3", white: "D65", toXYZ_M: [[0.4865709486482162, 0.26566769316909306, 0.1982172852343625], [0.2289745640697488, 0.6917385218365064, 0.079286914093745], [0, 0.04511338185890264, 1.043944368900976]], fromXYZ_M: [[2.493496911941425, -0.9313836179191239, -0.40271078445071684], [-0.8294889695615747, 1.7626640603183463, 0.023624685841943577], [0.03584583024378447, -0.07617238926804182, 0.9568845240076872]] });
          const kn = [[3.2409699419045226, -1.537383177570094, -0.4986107602930034], [-0.9692436362808796, 1.8759675015077202, 0.04155505740717559], [0.05563007969699366, -0.20397695888897652, 1.0569715142428786]];
          var _n = new Pt({ id: "srgb-linear", name: "Linear sRGB", white: "D65", toXYZ_M: [[0.41239079926595934, 0.357584339383878, 0.1804807884018343], [0.21263900587151027, 0.715168678767756, 0.07219231536073371], [0.01933081871559182, 0.11919477979462598, 0.9505321522496607]], fromXYZ_M: kn }), Mn = { aliceblue: [240 / 255, 248 / 255, 1], antiquewhite: [250 / 255, 235 / 255, 215 / 255], aqua: [0, 1, 1], aquamarine: [127 / 255, 1, 212 / 255], azure: [240 / 255, 1, 1], beige: [245 / 255, 245 / 255, 220 / 255], bisque: [1, 228 / 255, 196 / 255], black: [0, 0, 0], blanchedalmond: [1, 235 / 255, 205 / 255], blue: [0, 0, 1], blueviolet: [138 / 255, 43 / 255, 226 / 255], brown: [165 / 255, 42 / 255, 42 / 255], burlywood: [222 / 255, 184 / 255, 135 / 255], cadetblue: [95 / 255, 158 / 255, 160 / 255], chartreuse: [127 / 255, 1, 0], chocolate: [210 / 255, 105 / 255, 30 / 255], coral: [1, 127 / 255, 80 / 255], cornflowerblue: [100 / 255, 149 / 255, 237 / 255], cornsilk: [1, 248 / 255, 220 / 255], crimson: [220 / 255, 20 / 255, 60 / 255], cyan: [0, 1, 1], darkblue: [0, 0, 139 / 255], darkcyan: [0, 139 / 255, 139 / 255], darkgoldenrod: [184 / 255, 134 / 255, 11 / 255], darkgray: [169 / 255, 169 / 255, 169 / 255], darkgreen: [0, 100 / 255, 0], darkgrey: [169 / 255, 169 / 255, 169 / 255], darkkhaki: [189 / 255, 183 / 255, 107 / 255], darkmagenta: [139 / 255, 0, 139 / 255], darkolivegreen: [85 / 255, 107 / 255, 47 / 255], darkorange: [1, 140 / 255, 0], darkorchid: [0.6, 50 / 255, 0.8], darkred: [139 / 255, 0, 0], darksalmon: [233 / 255, 150 / 255, 122 / 255], darkseagreen: [143 / 255, 188 / 255, 143 / 255], darkslateblue: [72 / 255, 61 / 255, 139 / 255], darkslategray: [47 / 255, 79 / 255, 79 / 255], darkslategrey: [47 / 255, 79 / 255, 79 / 255], darkturquoise: [0, 206 / 255, 209 / 255], darkviolet: [148 / 255, 0, 211 / 255], deeppink: [1, 20 / 255, 147 / 255], deepskyblue: [0, 191 / 255, 1], dimgray: [105 / 255, 105 / 255, 105 / 255], dimgrey: [105 / 255, 105 / 255, 105 / 255], dodgerblue: [30 / 255, 144 / 255, 1], firebrick: [178 / 255, 34 / 255, 34 / 255], floralwhite: [1, 250 / 255, 240 / 255], forestgreen: [34 / 255, 139 / 255, 34 / 255], fuchsia: [1, 0, 1], gainsboro: [220 / 255, 220 / 255, 220 / 255], ghostwhite: [248 / 255, 248 / 255, 1], gold: [1, 215 / 255, 0], goldenrod: [218 / 255, 165 / 255, 32 / 255], gray: [128 / 255, 128 / 255, 128 / 255], green: [0, 128 / 255, 0], greenyellow: [173 / 255, 1, 47 / 255], grey: [128 / 255, 128 / 255, 128 / 255], honeydew: [240 / 255, 1, 240 / 255], hotpink: [1, 105 / 255, 180 / 255], indianred: [205 / 255, 92 / 255, 92 / 255], indigo: [75 / 255, 0, 130 / 255], ivory: [1, 1, 240 / 255], khaki: [240 / 255, 230 / 255, 140 / 255], lavender: [230 / 255, 230 / 255, 250 / 255], lavenderblush: [1, 240 / 255, 245 / 255], lawngreen: [124 / 255, 252 / 255, 0], lemonchiffon: [1, 250 / 255, 205 / 255], lightblue: [173 / 255, 216 / 255, 230 / 255], lightcoral: [240 / 255, 128 / 255, 128 / 255], lightcyan: [224 / 255, 1, 1], lightgoldenrodyellow: [250 / 255, 250 / 255, 210 / 255], lightgray: [211 / 255, 211 / 255, 211 / 255], lightgreen: [144 / 255, 238 / 255, 144 / 255], lightgrey: [211 / 255, 211 / 255, 211 / 255], lightpink: [1, 182 / 255, 193 / 255], lightsalmon: [1, 160 / 255, 122 / 255], lightseagreen: [32 / 255, 178 / 255, 170 / 255], lightskyblue: [135 / 255, 206 / 255, 250 / 255], lightslategray: [119 / 255, 136 / 255, 0.6], lightslategrey: [119 / 255, 136 / 255, 0.6], lightsteelblue: [176 / 255, 196 / 255, 222 / 255], lightyellow: [1, 1, 224 / 255], lime: [0, 1, 0], limegreen: [50 / 255, 205 / 255, 50 / 255], linen: [250 / 255, 240 / 255, 230 / 255], magenta: [1, 0, 1], maroon: [128 / 255, 0, 0], mediumaquamarine: [0.4, 205 / 255, 170 / 255], mediumblue: [0, 0, 205 / 255], mediumorchid: [186 / 255, 85 / 255, 211 / 255], mediumpurple: [147 / 255, 112 / 255, 219 / 255], mediumseagreen: [60 / 255, 179 / 255, 113 / 255], mediumslateblue: [123 / 255, 104 / 255, 238 / 255], mediumspringgreen: [0, 250 / 255, 154 / 255], mediumturquoise: [72 / 255, 209 / 255, 0.8], mediumvioletred: [199 / 255, 21 / 255, 133 / 255], midnightblue: [25 / 255, 25 / 255, 112 / 255], mintcream: [245 / 255, 1, 250 / 255], mistyrose: [1, 228 / 255, 225 / 255], moccasin: [1, 228 / 255, 181 / 255], navajowhite: [1, 222 / 255, 173 / 255], navy: [0, 0, 128 / 255], oldlace: [253 / 255, 245 / 255, 230 / 255], olive: [128 / 255, 128 / 255, 0], olivedrab: [107 / 255, 142 / 255, 35 / 255], orange: [1, 165 / 255, 0], orangered: [1, 69 / 255, 0], orchid: [218 / 255, 112 / 255, 214 / 255], palegoldenrod: [238 / 255, 232 / 255, 170 / 255], palegreen: [152 / 255, 251 / 255, 152 / 255], paleturquoise: [175 / 255, 238 / 255, 238 / 255], palevioletred: [219 / 255, 112 / 255, 147 / 255], papayawhip: [1, 239 / 255, 213 / 255], peachpuff: [1, 218 / 255, 185 / 255], peru: [205 / 255, 133 / 255, 63 / 255], pink: [1, 192 / 255, 203 / 255], plum: [221 / 255, 160 / 255, 221 / 255], powderblue: [176 / 255, 224 / 255, 230 / 255], purple: [128 / 255, 0, 128 / 255], rebeccapurple: [0.4, 0.2, 0.6], red: [1, 0, 0], rosybrown: [188 / 255, 143 / 255, 143 / 255], royalblue: [65 / 255, 105 / 255, 225 / 255], saddlebrown: [139 / 255, 69 / 255, 19 / 255], salmon: [250 / 255, 128 / 255, 114 / 255], sandybrown: [244 / 255, 164 / 255, 96 / 255], seagreen: [46 / 255, 139 / 255, 87 / 255], seashell: [1, 245 / 255, 238 / 255], sienna: [160 / 255, 82 / 255, 45 / 255], silver: [192 / 255, 192 / 255, 192 / 255], skyblue: [135 / 255, 206 / 255, 235 / 255], slateblue: [106 / 255, 90 / 255, 205 / 255], slategray: [112 / 255, 128 / 255, 144 / 255], slategrey: [112 / 255, 128 / 255, 144 / 255], snow: [1, 250 / 255, 250 / 255], springgreen: [0, 1, 127 / 255], steelblue: [70 / 255, 130 / 255, 180 / 255], tan: [210 / 255, 180 / 255, 140 / 255], teal: [0, 128 / 255, 128 / 255], thistle: [216 / 255, 191 / 255, 216 / 255], tomato: [1, 99 / 255, 71 / 255], turquoise: [64 / 255, 224 / 255, 208 / 255], violet: [238 / 255, 130 / 255, 238 / 255], wheat: [245 / 255, 222 / 255, 179 / 255], white: [1, 1, 1], whitesmoke: [245 / 255, 245 / 255, 245 / 255], yellow: [1, 1, 0], yellowgreen: [154 / 255, 205 / 255, 50 / 255] };
          let Sn = Array(3).fill("<percentage> | <number>[0, 255]"), En = Array(3).fill("<number>[0, 255]");
          var Cn = new Pt({ id: "srgb", name: "sRGB", base: _n, fromBase: (e3) => e3.map((e4) => {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 > 31308e-7 ? t3 * (1.055 * r2 ** (1 / 2.4) - 0.055) : 12.92 * e4;
          }), toBase: (e3) => e3.map((e4) => {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 <= 0.04045 ? e4 / 12.92 : t3 * ((r2 + 0.055) / 1.055) ** 2.4;
          }), formats: { rgb: { coords: Sn }, rgb_number: { name: "rgb", commas: true, coords: En, alpha: false }, color: {}, rgba: { coords: Sn, commas: true, alpha: true }, rgba_number: { name: "rgba", commas: true, coords: En }, hex: { type: "custom", toGamut: true, test: (e3) => /^#(([a-f0-9]{2}){3,4}|[a-f0-9]{3,4})$/i.test(e3), parse(e3) {
            e3.length <= 5 && (e3 = e3.replace(/[a-f0-9]/gi, "$&$&"));
            let t3 = [];
            return e3.replace(/[a-f0-9]{2}/gi, (e4) => {
              t3.push(parseInt(e4, 16) / 255);
            }), { spaceId: "srgb", coords: t3.slice(0, 3), alpha: t3.slice(3)[0] };
          }, serialize: (e3, t3, { collapse: r2 = true, alpha: n2 } = {}) => {
            (false !== n2 && t3 < 1 || true === n2) && e3.push(t3), e3 = e3.map((e4) => Math.round(255 * e4));
            let o2 = r2 && e3.every((e4) => e4 % 17 == 0), a2 = e3.map((e4) => o2 ? (e4 / 17).toString(16) : e4.toString(16).padStart(2, "0")).join("");
            return "#" + a2;
          } }, keyword: { type: "custom", test: (e3) => /^[a-z]+$/i.test(e3), parse(e3) {
            let t3 = { spaceId: "srgb", coords: null, alpha: 1 };
            if ("transparent" === (e3 = e3.toLowerCase()) ? (t3.coords = Mn.black, t3.alpha = 0) : t3.coords = Mn[e3], t3.coords) return t3;
          } } } }), xn = new Pt({ id: "p3", cssId: "display-p3", name: "P3", base: vn, fromBase: Cn.fromBase, toBase: Cn.toBase });
          let On;
          if (vt.display_space = Cn, "undefined" != typeof CSS && CSS.supports) for (let e3 of [Gt, wn, xn]) {
            let t3 = e3.getMinCoords(), r2 = bn({ space: e3, coords: t3, alpha: 1 });
            if (CSS.supports("color", r2)) {
              vt.display_space = e3;
              break;
            }
          }
          function jn(e3, t3) {
            return it(e3) || it(t3) ? e3 === t3 ? null : 0 : e3 - t3;
          }
          function Rn(e3) {
            return Dt(e3, [Bt, "y"]);
          }
          function An(e3, t3) {
            It(e3, [Bt, "y"], t3);
          }
          var Tn = Object.freeze({ __proto__: null, getLuminance: Rn, register: function(e3) {
            Object.defineProperty(e3.prototype, "luminance", { get() {
              return Rn(this);
            }, set(e4) {
              An(this, e4);
            } });
          }, setLuminance: An });
          function Bn(e3) {
            return e3 >= 0.022 ? e3 : e3 + (0.022 - e3) ** 1.414;
          }
          function Pn(e3) {
            let t3 = e3 < 0 ? -1 : 1, r2 = Math.abs(e3);
            return t3 * Math.pow(r2, 2.4);
          }
          const Nn = 216 / 24389, Ln = 24 / 116, Dn = 24389 / 27;
          let Fn = St.D65;
          var In = new At({ id: "lab-d65", name: "Lab D65", coords: { l: { refRange: [0, 100], name: "Lightness" }, a: { refRange: [-125, 125] }, b: { refRange: [-125, 125] } }, white: Fn, base: Bt, fromBase(e3) {
            let t3 = e3.map((e4, t4) => e4 / Fn[t4]), r2 = t3.map((e4) => e4 > Nn ? Math.cbrt(e4) : (Dn * e4 + 16) / 116);
            return [116 * r2[1] - 16, 500 * (r2[0] - r2[1]), 200 * (r2[1] - r2[2])];
          }, toBase(e3) {
            let t3 = [];
            return t3[1] = (e3[0] + 16) / 116, t3[0] = e3[1] / 500 + t3[1], t3[2] = t3[1] - e3[2] / 200, [t3[0] > Ln ? Math.pow(t3[0], 3) : (116 * t3[0] - 16) / Dn, e3[0] > 8 ? Math.pow((e3[0] + 16) / 116, 3) : e3[0] / Dn, t3[2] > Ln ? Math.pow(t3[2], 3) : (116 * t3[2] - 16) / Dn].map((e4, t4) => e4 * Fn[t4]);
          }, formats: { "lab-d65": { coords: ["<number> | <percentage>", "<number> | <percentage>", "<number> | <percentage>"] } } });
          const $n = 0.5 * Math.pow(5, 0.5) + 0.5;
          var zn = Object.freeze({ __proto__: null, contrastAPCA: function(e3, t3) {
            let r2, n2, o2, a2, i2, s2;
            t3 = Rt(t3), e3 = Rt(e3), t3 = mn(t3, "srgb"), [a2, i2, s2] = t3.coords.map((e4) => it(e4) ? 0 : e4);
            let l2 = 0.2126729 * Pn(a2) + 0.7151522 * Pn(i2) + 0.072175 * Pn(s2);
            e3 = mn(e3, "srgb"), [a2, i2, s2] = e3.coords.map((e4) => it(e4) ? 0 : e4);
            let c2 = 0.2126729 * Pn(a2) + 0.7151522 * Pn(i2) + 0.072175 * Pn(s2), u2 = Bn(l2), h2 = Bn(c2), f2 = h2 > u2;
            return Math.abs(h2 - u2) < 5e-4 ? n2 = 0 : f2 ? (r2 = h2 ** 0.56 - u2 ** 0.57, n2 = 1.14 * r2) : (r2 = h2 ** 0.65 - u2 ** 0.62, n2 = 1.14 * r2), o2 = Math.abs(n2) < 0.1 ? 0 : n2 > 0 ? n2 - 0.027 : n2 + 0.027, 100 * o2;
          }, contrastDeltaPhi: function(e3, t3) {
            e3 = Rt(e3), t3 = Rt(t3);
            let r2 = Dt(e3, [In, "l"]), n2 = Dt(t3, [In, "l"]), o2 = Math.abs(Math.pow(r2, $n) - Math.pow(n2, $n)), a2 = Math.pow(o2, 1 / $n) * Math.SQRT2 - 40;
            return a2 < 7.5 ? 0 : a2;
          }, contrastLstar: function(e3, t3) {
            e3 = Rt(e3), t3 = Rt(t3);
            let r2 = Dt(e3, [Gt, "l"]), n2 = Dt(t3, [Gt, "l"]);
            return Math.abs(r2 - n2);
          }, contrastMichelson: function(e3, t3) {
            e3 = Rt(e3), t3 = Rt(t3);
            let r2 = Math.max(Rn(e3), 0), n2 = Math.max(Rn(t3), 0);
            n2 > r2 && ([r2, n2] = [n2, r2]);
            let o2 = r2 + n2;
            return 0 === o2 ? 0 : (r2 - n2) / o2;
          }, contrastWCAG21: function(e3, t3) {
            e3 = Rt(e3), t3 = Rt(t3);
            let r2 = Math.max(Rn(e3), 0), n2 = Math.max(Rn(t3), 0);
            return n2 > r2 && ([r2, n2] = [n2, r2]), (r2 + 0.05) / (n2 + 0.05);
          }, contrastWeber: function(e3, t3) {
            e3 = Rt(e3), t3 = Rt(t3);
            let r2 = Math.max(Rn(e3), 0), n2 = Math.max(Rn(t3), 0);
            return n2 > r2 && ([r2, n2] = [n2, r2]), 0 === n2 ? 5e4 : (r2 - n2) / n2;
          } });
          function qn(e3) {
            let [t3, r2, n2] = Lt(e3, Bt), o2 = t3 + 15 * r2 + 3 * n2;
            return [4 * t3 / o2, 9 * r2 / o2];
          }
          function Hn(e3) {
            let [t3, r2, n2] = Lt(e3, Bt), o2 = t3 + r2 + n2;
            return [t3 / o2, r2 / o2];
          }
          var Wn = Object.freeze({ __proto__: null, register: function(e3) {
            Object.defineProperty(e3.prototype, "uv", { get() {
              return qn(this);
            } }), Object.defineProperty(e3.prototype, "xy", { get() {
              return Hn(this);
            } });
          }, uv: qn, xy: Hn });
          function Gn(e3, t3, r2 = {}) {
            nt(r2) && (r2 = { method: r2 });
            let _a3 = r2, { method: n2 = vt.deltaE } = _a3, o2 = __objRest(_a3, ["method"]);
            for (let r3 in fn) if ("deltae" + n2.toLowerCase() === r3.toLowerCase()) return fn[r3](e3, t3, o2);
            throw new TypeError(`Unknown deltaE method: ${n2}`);
          }
          function Yn(e3, t3 = 0.25) {
            return It(e3, [At.get("oklch", "lch"), "l"], (e4) => e4 * (1 + t3));
          }
          function Un(e3, t3 = 0.25) {
            return It(e3, [At.get("oklch", "lch"), "l"], (e4) => e4 * (1 - t3));
          }
          Yn.returns = "color", Un.returns = "color";
          var Vn = Object.freeze({ __proto__: null, darken: Un, lighten: Yn });
          function Jn(e3, t3, r2, n2 = {}) {
            return [e3, t3] = [Rt(e3), Rt(t3)], "object" === ot(r2) && ([r2, n2] = [0.5, r2]), Kn(e3, t3, n2)(r2 != null ? r2 : 0.5);
          }
          function Xn(e3, t3, r2 = {}) {
            let n2;
            Zn(e3) && ([n2, r2] = [e3, t3], [e3, t3] = n2.rangeArgs.colors);
            let _a3 = r2, { maxDeltaE: o2, deltaEMethod: a2, steps: i2 = 2, maxSteps: s2 = 1e3 } = _a3, l2 = __objRest(_a3, ["maxDeltaE", "deltaEMethod", "steps", "maxSteps"]);
            n2 || ([e3, t3] = [Rt(e3), Rt(t3)], n2 = Kn(e3, t3, l2));
            let c2 = Gn(e3, t3), u2 = o2 > 0 ? Math.max(i2, Math.ceil(c2 / o2) + 1) : i2, h2 = [];
            if (void 0 !== s2 && (u2 = Math.min(u2, s2)), 1 === u2) h2 = [{ p: 0.5, color: n2(0.5) }];
            else {
              let e4 = 1 / (u2 - 1);
              h2 = Array.from({ length: u2 }, (t4, r3) => {
                let o3 = r3 * e4;
                return { p: o3, color: n2(o3) };
              });
            }
            if (o2 > 0) {
              let e4 = h2.reduce((e5, t4, r3) => {
                if (0 === r3) return 0;
                let n3 = Gn(t4.color, h2[r3 - 1].color, a2);
                return Math.max(e5, n3);
              }, 0);
              for (; e4 > o2; ) {
                e4 = 0;
                for (let t4 = 1; t4 < h2.length && h2.length < s2; t4++) {
                  let r3 = h2[t4 - 1], o3 = h2[t4], a3 = (o3.p + r3.p) / 2, i3 = n2(a3);
                  e4 = Math.max(e4, Gn(i3, r3.color), Gn(i3, o3.color)), h2.splice(t4, 0, { p: a3, color: n2(a3) }), t4++;
                }
              }
            }
            return h2 = h2.map((e4) => e4.color), h2;
          }
          function Kn(e3, t3, r2 = {}) {
            if (Zn(e3)) {
              let [r3, n3] = [e3, t3];
              return Kn(...r3.rangeArgs.colors, __spreadValues(__spreadValues({}, r3.rangeArgs.options), n3));
            }
            let { space: n2, outputSpace: o2, progression: a2, premultiplied: i2 } = r2;
            e3 = Rt(e3), t3 = Rt(t3), e3 = lr(e3), t3 = lr(t3);
            let s2 = { colors: [e3, t3], options: r2 };
            if (n2 = n2 ? At.get(n2) : At.registry[vt.interpolationSpace] || e3.space, o2 = o2 ? At.get(o2) : n2, e3 = mn(e3, n2), t3 = mn(t3, n2), e3 = dn(e3), t3 = dn(t3), n2.coords.h && "angle" === n2.coords.h.type) {
              let o3 = r2.hue = r2.hue || "shorter", a3 = [n2, "h"], [i3, s3] = [Dt(e3, a3), Dt(t3, a3)];
              it(i3) && !it(s3) ? i3 = s3 : it(s3) && !it(i3) && (s3 = i3), [i3, s3] = Ut(o3, [i3, s3]), It(e3, a3, i3), It(t3, a3, s3);
            }
            return i2 && (e3.coords = e3.coords.map((t4) => t4 * e3.alpha), t3.coords = t3.coords.map((e4) => e4 * t3.alpha)), Object.assign((r3) => {
              r3 = a2 ? a2(r3) : r3;
              let s3 = e3.coords.map((e4, n3) => ct(e4, t3.coords[n3], r3)), l2 = ct(e3.alpha, t3.alpha, r3), c2 = { space: n2, coords: s3, alpha: l2 };
              return i2 && (c2.coords = c2.coords.map((e4) => e4 / l2)), o2 !== n2 && (c2 = mn(c2, o2)), c2;
            }, { rangeArgs: s2 });
          }
          function Zn(e3) {
            return "function" === ot(e3) && !!e3.rangeArgs;
          }
          vt.interpolationSpace = "lab";
          var Qn = Object.freeze({ __proto__: null, isRange: Zn, mix: Jn, range: Kn, register: function(e3) {
            e3.defineFunction("mix", Jn, { returns: "color" }), e3.defineFunction("range", Kn, { returns: "function<color>" }), e3.defineFunction("steps", Xn, { returns: "array<color>" });
          }, steps: Xn }), eo = new At({ id: "hsl", name: "HSL", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 100], name: "Saturation" }, l: { range: [0, 100], name: "Lightness" } }, base: Cn, fromBase: (e3) => {
            let t3 = Math.max(...e3), r2 = Math.min(...e3), [n2, o2, a2] = e3, [i2, s2, l2] = [null, 0, (r2 + t3) / 2], c2 = t3 - r2;
            if (0 !== c2) {
              switch (s2 = 0 === l2 || 1 === l2 ? 0 : (t3 - l2) / Math.min(l2, 1 - l2), t3) {
                case n2:
                  i2 = (o2 - a2) / c2 + (o2 < a2 ? 6 : 0);
                  break;
                case o2:
                  i2 = (a2 - n2) / c2 + 2;
                  break;
                case a2:
                  i2 = (n2 - o2) / c2 + 4;
              }
              i2 *= 60;
            }
            return s2 < 0 && (i2 += 180, s2 = Math.abs(s2)), i2 >= 360 && (i2 -= 360), [i2, 100 * s2, 100 * l2];
          }, toBase: (e3) => {
            let [t3, r2, n2] = e3;
            function o2(e4) {
              let o3 = (e4 + t3 / 30) % 12, a2 = r2 * Math.min(n2, 1 - n2);
              return n2 - a2 * Math.max(-1, Math.min(o3 - 3, 9 - o3, 1));
            }
            return t3 %= 360, t3 < 0 && (t3 += 360), r2 /= 100, n2 /= 100, [o2(0), o2(8), o2(4)];
          }, formats: { hsl: { coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] }, hsla: { coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"], commas: true, alpha: true } } }), to = new At({ id: "hsv", name: "HSV", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 100], name: "Saturation" }, v: { range: [0, 100], name: "Value" } }, base: Cn, fromBase(e3) {
            let t3 = Math.max(...e3), r2 = Math.min(...e3), [n2, o2, a2] = e3, [i2, s2, l2] = [null, 0, t3], c2 = t3 - r2;
            if (0 !== c2) {
              switch (t3) {
                case n2:
                  i2 = (o2 - a2) / c2 + (o2 < a2 ? 6 : 0);
                  break;
                case o2:
                  i2 = (a2 - n2) / c2 + 2;
                  break;
                case a2:
                  i2 = (n2 - o2) / c2 + 4;
              }
              i2 *= 60;
            }
            return l2 && (s2 = c2 / l2), i2 >= 360 && (i2 -= 360), [i2, 100 * s2, 100 * l2];
          }, toBase(e3) {
            let [t3, r2, n2] = e3;
            function o2(e4) {
              let o3 = (e4 + t3 / 60) % 6;
              return n2 - n2 * r2 * Math.max(0, Math.min(o3, 4 - o3, 1));
            }
            return t3 %= 360, t3 < 0 && (t3 += 360), r2 /= 100, n2 /= 100, [o2(5), o2(3), o2(1)];
          }, formats: { color: { id: "--hsv", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } }), ro = new At({ id: "hwb", name: "HWB", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, w: { range: [0, 100], name: "Whiteness" }, b: { range: [0, 100], name: "Blackness" } }, base: to, fromBase(e3) {
            let [t3, r2, n2] = e3;
            return [t3, n2 * (100 - r2) / 100, 100 - n2];
          }, toBase(e3) {
            let [t3, r2, n2] = e3;
            r2 /= 100, n2 /= 100;
            let o2 = r2 + n2;
            if (o2 >= 1) return [t3, 0, r2 / o2 * 100];
            let a2 = 1 - n2;
            return [t3, 100 * (0 === a2 ? 0 : 1 - r2 / a2), 100 * a2];
          }, formats: { hwb: { coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } }), no = new Pt({ id: "a98rgb-linear", cssId: "--a98-rgb-linear", name: "Linear Adobe\xAE 98 RGB compatible", white: "D65", toXYZ_M: [[0.5766690429101305, 0.1855582379065463, 0.1882286462349947], [0.29734497525053605, 0.6273635662554661, 0.07529145849399788], [0.02703136138641234, 0.07068885253582723, 0.9913375368376388]], fromXYZ_M: [[2.0415879038107465, -0.5650069742788596, -0.34473135077832956], [-0.9692436362808795, 1.8759675015077202, 0.04155505740717557], [0.013444280632031142, -0.11836239223101838, 1.0151749943912054]] }), oo = new Pt({ id: "a98rgb", cssId: "a98-rgb", name: "Adobe\xAE 98 RGB compatible", base: no, toBase: (e3) => e3.map((e4) => Math.pow(Math.abs(e4), 563 / 256) * Math.sign(e4)), fromBase: (e3) => e3.map((e4) => Math.pow(Math.abs(e4), 256 / 563) * Math.sign(e4)) }), ao = new Pt({ id: "prophoto-linear", cssId: "--prophoto-rgb-linear", name: "Linear ProPhoto", white: "D50", base: $t, toXYZ_M: [[0.7977666449006423, 0.13518129740053308, 0.0313477341283922], [0.2880748288194013, 0.711835234241873, 8993693872564e-17], [0, 0, 0.8251046025104602]], fromXYZ_M: [[1.3457868816471583, -0.25557208737979464, -0.05110186497554526], [-0.5446307051249019, 1.5082477428451468, 0.02052744743642139], [0, 0, 1.2119675456389452]] });
          const io = 1 / 512;
          var so = new Pt({ id: "prophoto", cssId: "prophoto-rgb", name: "ProPhoto", base: ao, toBase: (e3) => e3.map((e4) => {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 < 0.03125 ? e4 / 16 : t3 * r2 ** 1.8;
          }), fromBase: (e3) => e3.map((e4) => {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 >= io ? t3 * r2 ** (1 / 1.8) : 16 * e4;
          }) });
          const lo = 1.09929682680944, co = 0.018053968510807;
          var uo = new Pt({ id: "--rec2020-oetf", name: "REC.2020_Scene_Referred", base: yn, referred: "scene", toBase: (e3) => e3.map(function(e4) {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 < 4.5 * co ? e4 / 4.5 : t3 * Math.pow((r2 + lo - 1) / lo, 1 / 0.45);
          }), fromBase: (e3) => e3.map(function(e4) {
            let t3 = e4 < 0 ? -1 : 1, r2 = e4 * t3;
            return r2 >= co ? t3 * (lo * Math.pow(r2, 0.45) - (lo - 1)) : 4.5 * e4;
          }) }), ho = new At({ id: "oklch", name: "OkLCh", coords: { l: { refRange: [0, 1], name: "Lightness" }, c: { refRange: [0, 0.4], name: "Chroma" }, h: { refRange: [0, 360], type: "angle", name: "Hue" } }, white: "D65", base: ar, fromBase: Vt.fromBase, toBase: Vt.toBase, formats: { oklch: { coords: ["<percentage> | <number>", "<number> | <percentage>", "<number> | <angle>"] } } });
          const fo = 2 * Math.PI, po = [[4.076741636075958, -3.307711539258063, 0.2309699031821043], [-1.2684379732850315, 2.609757349287688, -0.341319376002657], [-0.0041960761386756, -0.7034186179359362, 1.7076146940746117]], go = [[[-1.8817031, -0.80936501], [1.19086277, 1.76576728, 0.59662641, 0.75515197, 0.56771245]], [[1.8144408, -1.19445267], [0.73956515, -0.45954404, 0.08285427, 0.12541073, -0.14503204]], [[0.13110758, 1.81333971], [1.35733652, -915799e-8, -1.1513021, -0.50559606, 692167e-8]]], mo = Number.MAX_VALUE, bo = 0.206, yo = (1 + bo) / 1.03;
          function wo(e3, t3) {
            let r2 = e3.length;
            if (r2 !== t3.length) throw new Error(`Vectors of size ${r2} and ${t3.length} are not aligned`);
            let n2 = 0;
            return e3.forEach((e4, r3) => {
              n2 += e4 * t3[r3];
            }), n2;
          }
          function vo(e3) {
            return 0.5 * (yo * e3 - bo + Math.sqrt((yo * e3 - bo) * (yo * e3 - bo) + 0.12 * yo * e3));
          }
          function ko(e3) {
            return (e3 ** 2 + bo * e3) / (yo * (e3 + 0.03));
          }
          function _o(e3) {
            let [t3, r2] = e3;
            return [r2 / t3, r2 / (1 - t3)];
          }
          function Mo(e3, t3) {
            let r2 = rt(e3, or);
            return r2[0] = r2[0] ** 3, r2[1] = r2[1] ** 3, r2[2] = r2[2] ** 3, rt(r2, t3, r2);
          }
          function So(e3, t3, r2, n2) {
            let o2 = function(e4, t4, r3, n3) {
              let o3, a3, i3, s2, l2, c2, u2, h2;
              wo(n3[0][0], [e4, t4]) > 1 ? ([o3, a3, i3, s2, l2] = n3[0][1], [c2, u2, h2] = r3[0]) : wo(n3[1][0], [e4, t4]) > 1 ? ([o3, a3, i3, s2, l2] = n3[1][1], [c2, u2, h2] = r3[1]) : ([o3, a3, i3, s2, l2] = n3[2][1], [c2, u2, h2] = r3[2]);
              let f2 = o3 + a3 * e4 + i3 * t4 + s2 * e4 ** 2 + l2 * e4 * t4, p2 = wo(or[0].slice(1), [e4, t4]), d2 = wo(or[1].slice(1), [e4, t4]), g2 = wo(or[2].slice(1), [e4, t4]), m2 = 1 + f2 * p2, b2 = 1 + f2 * d2, y2 = 1 + f2 * g2, w2 = c2 * m2 ** 3 + u2 * b2 ** 3 + h2 * y2 ** 3, v2 = c2 * (3 * p2 * m2 ** 2) + u2 * (3 * d2 * b2 ** 2) + h2 * (3 * g2 * y2 ** 2);
              return f2 -= w2 * v2 / (v2 ** 2 - 0.5 * w2 * (c2 * (6 * p2 ** 2 * m2) + u2 * (6 * d2 ** 2 * b2) + h2 * (6 * g2 ** 2 * y2))), f2;
            }(e3, t3, r2, n2), a2 = Mo([1, o2 * e3, o2 * t3], r2), i2 = dt(1 / Math.max(...a2), 1 / 3);
            return [i2, i2 * o2];
          }
          function Eo(e3, t3, r2) {
            let [n2, o2, a2] = e3, i2 = So(o2, a2, t3, r2), s2 = function(e4, t4, r3, n3, o3, a3, i3, s3) {
              let l3;
              if (void 0 === s3 && (s3 = So(e4, t4, a3, i3)), (r3 - o3) * s3[1] - 1 * (s3[0] - o3) <= 0) l3 = s3[1] * o3 / (1 * s3[0] + s3[1] * (o3 - r3));
              else {
                l3 = s3[1] * (o3 - 1) / (1 * (s3[0] - 1) + s3[1] * (o3 - r3));
                let n4 = r3 - o3, i4 = 1, c3 = wo(or[0].slice(1), [e4, t4]), u3 = wo(or[1].slice(1), [e4, t4]), h3 = wo(or[2].slice(1), [e4, t4]), f3 = n4 + i4 * c3, p3 = n4 + i4 * u3, d2 = n4 + i4 * h3, g2 = o3 * (1 - l3) + l3 * r3, m2 = 1 * l3, b2 = g2 + m2 * c3, y2 = g2 + m2 * u3, w2 = g2 + m2 * h3, v2 = b2 ** 3, k2 = y2 ** 3, _2 = w2 ** 3, M2 = 3 * f3 * b2 ** 2, S2 = 3 * p3 * y2 ** 2, E2 = 3 * d2 * w2 ** 2, C2 = 6 * f3 ** 2 * b2, x2 = 6 * p3 ** 2 * y2, O2 = 6 * d2 ** 2 * w2, j2 = wo(a3[0], [v2, k2, _2]) - 1, R2 = wo(a3[0], [M2, S2, E2]), A2 = R2 / (R2 * R2 - 0.5 * j2 * wo(a3[0], [C2, x2, O2])), T2 = -j2 * A2, B2 = wo(a3[1], [v2, k2, _2]) - 1, P2 = wo(a3[1], [M2, S2, E2]), N2 = P2 / (P2 * P2 - 0.5 * B2 * wo(a3[1], [C2, x2, O2])), L2 = -B2 * N2, D2 = wo(a3[2], [v2, k2, _2]) - 1, F2 = wo(a3[2], [M2, S2, E2]), I2 = F2 / (F2 * F2 - 0.5 * D2 * wo(a3[2], [C2, x2, O2])), $2 = -D2 * I2;
                T2 = A2 >= 0 ? T2 : mo, L2 = N2 >= 0 ? L2 : mo, $2 = I2 >= 0 ? $2 : mo, l3 += Math.min(T2, Math.min(L2, $2));
              }
              return l3;
            }(o2, a2, n2, 0, n2, t3, r2, i2), l2 = _o(i2), c2 = s2 / Math.min(n2 * l2[0], (1 - n2) * l2[1]), u2 = function(e4, t4) {
              return [0.11516993 + 1 / (7.4477897 + 4.1590124 * t4 + e4 * (1.75198401 * t4 - 2.19557347 + e4 * (-2.13704948 - 10.02301043 * t4 + e4 * (5.38770819 * t4 - 4.24894561 + 4.69891013 * e4)))), 0.11239642 + 1 / (1.6132032 - 0.68124379 * t4 + e4 * (0.40370612 + 0.90148123 * t4 + e4 * (0.6122399 * t4 - 0.27087943 + e4 * (299215e-8 - 0.45399568 * t4 - 0.14661872 * e4))))];
            }(o2, a2), h2 = n2 * u2[0], f2 = (1 - n2) * u2[1], p2 = 0.9 * c2 * Math.sqrt(Math.sqrt(1 / (1 / h2 ** 4 + 1 / f2 ** 4)));
            return h2 = 0.4 * n2, f2 = 0.8 * (1 - n2), [Math.sqrt(1 / (1 / h2 ** 2 + 1 / f2 ** 2)), p2, s2];
          }
          var Co = new At({ id: "okhsl", name: "Okhsl", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 1], name: "Saturation" }, l: { range: [0, 1], name: "Lightness" } }, base: ar, gamutSpace: "self", fromBase: (e3) => function(e4, t3, r2) {
            let n2 = e4[0], o2 = 0, a2 = vo(n2), i2 = Math.sqrt(e4[1] ** 2 + e4[2] ** 2), s2 = 0.5 + Math.atan2(-e4[2], -e4[1]) / fo;
            if (0 !== a2 && 1 !== a2 && 0 !== i2) {
              let a3, s3, l3, c2, u2 = e4[1] / i2, h2 = e4[2] / i2, [f2, p2, d2] = Eo([n2, u2, h2], t3, r2), g2 = 0.8;
              i2 < p2 ? (s3 = g2 * f2, l3 = 1 - s3 / p2, c2 = i2 / (s3 + l3 * i2), o2 = c2 * g2) : (a3 = p2, s3 = 0.2 * p2 ** 2 * 1.5625 / f2, l3 = 1 - s3 / (d2 - p2), c2 = (i2 - a3) / (s3 + l3 * (i2 - a3)), o2 = g2 + 0.2 * c2);
            }
            const l2 = Math.abs(o2) < 1e-4;
            return l2 || 0 === a2 || Math.abs(1 - a2) < 1e-7 ? (s2 = null, l2 || (o2 = 0)) : s2 = Yt(360 * s2), [s2, o2, a2];
          }(e3, po, go), toBase: (e3) => function(e4, t3, r2) {
            let [n2, o2, a2] = e4, i2 = ko(a2), s2 = null, l2 = null;
            if (n2 = Yt(n2) / 360, 0 !== i2 && 1 !== i2 && 0 !== o2) {
              let e5, a3, c2, u2, h2 = Math.cos(fo * n2), f2 = Math.sin(fo * n2), [p2, d2, g2] = Eo([i2, h2, f2], t3, r2), m2 = 0.8;
              o2 < m2 ? (e5 = 1.25 * o2, a3 = 0, c2 = m2 * p2, u2 = 1 - c2 / d2) : (e5 = 5 * (o2 - 0.8), a3 = d2, c2 = 0.2 * d2 ** 2 * 1.5625 / p2, u2 = 1 - c2 / (g2 - d2));
              let b2 = a3 + e5 * c2 / (1 - u2 * e5);
              s2 = b2 * h2, l2 = b2 * f2;
            }
            return [i2, s2, l2];
          }(e3, po, go), formats: { color: { id: "--okhsl", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } }), xo = new At({ id: "oklrab", name: "Oklrab", coords: { l: { refRange: [0, 1], name: "Lightness" }, a: { refRange: [-0.4, 0.4] }, b: { refRange: [-0.4, 0.4] } }, white: "D65", base: ar, fromBase: (e3) => [vo(e3[0]), e3[1], e3[2]], toBase: (e3) => [ko(e3[0]), e3[1], e3[2]], formats: { color: { coords: ["<percentage> | <number>", "<number> | <percentage>[-1,1]", "<number> | <percentage>[-1,1]"] } } }), Oo = new At({ id: "oklrch", name: "Oklrch", coords: { l: { refRange: [0, 1], name: "Lightness" }, c: { refRange: [0, 0.4], name: "Chroma" }, h: { refRange: [0, 360], type: "angle", name: "Hue" } }, white: "D65", base: xo, fromBase: Vt.fromBase, toBase: Vt.toBase, formats: { color: { coords: ["<percentage> | <number>", "<number> | <percentage>[0,1]", "<number> | <angle>"] } } }), jo = new At({ id: "okhsv", name: "Okhsv", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 1], name: "Saturation" }, v: { range: [0, 1], name: "Value" } }, base: ar, gamutSpace: "self", fromBase: (e3) => function(e4, t3, r2) {
            let n2 = e4[0], o2 = 0, a2 = vo(n2), i2 = Math.sqrt(e4[1] ** 2 + e4[2] ** 2), s2 = 0.5 + Math.atan2(-e4[2], -e4[1]) / fo;
            if (0 !== n2 && 1 !== n2 && 0 !== i2) {
              let s3 = e4[1] / i2, l2 = e4[2] / i2, c2 = So(s3, l2, t3, r2), [u2, h2] = _o(c2), f2 = 0.5, p2 = 1 - f2 / u2, d2 = h2 / (i2 + n2 * h2), g2 = d2 * n2, m2 = d2 * i2, b2 = ko(g2), y2 = m2 * b2 / g2, [w2, v2, k2] = Mo([b2, s3 * y2, l2 * y2], t3), _2 = dt(1 / Math.max(Math.max(w2, v2), Math.max(k2, 0)), 1 / 3);
              n2 /= _2, i2 /= _2, i2 = i2 * vo(n2) / n2, n2 = vo(n2), a2 = n2 / g2, o2 = (f2 + h2) * m2 / (h2 * f2 + h2 * p2 * m2);
            }
            return s2 = Math.abs(o2) < 1e-4 || 0 === a2 ? null : Yt(360 * s2), [s2, o2, a2];
          }(e3, po, go), toBase: (e3) => function(e4, t3, r2) {
            let [n2, o2, a2] = e4;
            n2 = Yt(n2) / 360;
            let i2 = ko(a2), s2 = null, l2 = null;
            if (0 !== i2 && 0 !== o2) {
              let e5 = Math.cos(fo * n2), c2 = Math.sin(fo * n2), u2 = So(e5, c2, t3, r2), [h2, f2] = _o(u2), p2 = 0.5, d2 = 1 - p2 / h2, g2 = 1 - o2 * p2 / (p2 + f2 - f2 * d2 * o2), m2 = o2 * f2 * p2 / (p2 + f2 - f2 * d2 * o2);
              i2 = a2 * g2;
              let b2 = a2 * m2, y2 = ko(g2), w2 = m2 * y2 / g2, v2 = ko(i2);
              b2 = b2 * v2 / i2, i2 = v2;
              let [k2, _2, M2] = Mo([y2, e5 * w2, c2 * w2], t3), S2 = dt(1 / Math.max(Math.max(k2, _2), Math.max(M2, 0)), 1 / 3);
              i2 *= S2, b2 *= S2, s2 = b2 * e5, l2 = b2 * c2;
            }
            return [i2, s2, l2];
          }(e3, po, go), formats: { color: { id: "--okhsv", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } });
          let Ro = St.D65;
          const Ao = 216 / 24389, To = 24389 / 27, [Bo, Po] = qn({ space: Bt, coords: Ro });
          var No = new At({ id: "luv", name: "Luv", coords: { l: { refRange: [0, 100], name: "Lightness" }, u: { refRange: [-215, 215] }, v: { refRange: [-215, 215] } }, white: Ro, base: Bt, fromBase(e3) {
            let t3 = [st(e3[0]), st(e3[1]), st(e3[2])], r2 = t3[1], [n2, o2] = qn({ space: Bt, coords: t3 });
            if (!Number.isFinite(n2) || !Number.isFinite(o2)) return [0, 0, 0];
            let a2 = r2 <= Ao ? To * r2 : 116 * Math.cbrt(r2) - 16;
            return [a2, 13 * a2 * (n2 - Bo), 13 * a2 * (o2 - Po)];
          }, toBase(e3) {
            let [t3, r2, n2] = e3;
            if (0 === t3 || it(t3)) return [0, 0, 0];
            r2 = st(r2), n2 = st(n2);
            let o2 = r2 / (13 * t3) + Bo, a2 = n2 / (13 * t3) + Po, i2 = t3 <= 8 ? t3 / To : Math.pow((t3 + 16) / 116, 3);
            return [i2 * (9 * o2 / (4 * a2)), i2, i2 * ((12 - 3 * o2 - 20 * a2) / (4 * a2))];
          }, formats: { color: { id: "--luv", coords: ["<number> | <percentage>", "<number> | <percentage>", "<number> | <percentage>"] } } }), Lo = new At({ id: "lchuv", name: "LChuv", coords: { l: { refRange: [0, 100], name: "Lightness" }, c: { refRange: [0, 220], name: "Chroma" }, h: { refRange: [0, 360], type: "angle", name: "Hue" } }, base: No, fromBase: Vt.fromBase, toBase: Vt.toBase, formats: { color: { id: "--lchuv", coords: ["<number> | <percentage>", "<number> | <percentage>", "<number> | <angle>"] } } });
          const Do = 216 / 24389, Fo = 24389 / 27, Io = kn[0][0], $o = kn[0][1], zo = kn[0][2], qo = kn[1][0], Ho = kn[1][1], Wo = kn[1][2], Go = kn[2][0], Yo = kn[2][1], Uo = kn[2][2];
          function Vo(e3, t3, r2) {
            const n2 = t3 / (Math.sin(r2) - e3 * Math.cos(r2));
            return n2 < 0 ? 1 / 0 : n2;
          }
          function Jo(e3) {
            const t3 = Math.pow(e3 + 16, 3) / 1560896, r2 = t3 > Do ? t3 : e3 / Fo, n2 = r2 * (284517 * Io - 94839 * zo), o2 = r2 * (838422 * zo + 769860 * $o + 731718 * Io), a2 = r2 * (632260 * zo - 126452 * $o), i2 = r2 * (284517 * qo - 94839 * Wo), s2 = r2 * (838422 * Wo + 769860 * Ho + 731718 * qo), l2 = r2 * (632260 * Wo - 126452 * Ho), c2 = r2 * (284517 * Go - 94839 * Uo), u2 = r2 * (838422 * Uo + 769860 * Yo + 731718 * Go), h2 = r2 * (632260 * Uo - 126452 * Yo);
            return { r0s: n2 / a2, r0i: o2 * e3 / a2, r1s: n2 / (a2 + 126452), r1i: (o2 - 769860) * e3 / (a2 + 126452), g0s: i2 / l2, g0i: s2 * e3 / l2, g1s: i2 / (l2 + 126452), g1i: (s2 - 769860) * e3 / (l2 + 126452), b0s: c2 / h2, b0i: u2 * e3 / h2, b1s: c2 / (h2 + 126452), b1i: (u2 - 769860) * e3 / (h2 + 126452) };
          }
          function Xo(e3, t3) {
            const r2 = t3 / 360 * Math.PI * 2, n2 = Vo(e3.r0s, e3.r0i, r2), o2 = Vo(e3.r1s, e3.r1i, r2), a2 = Vo(e3.g0s, e3.g0i, r2), i2 = Vo(e3.g1s, e3.g1i, r2), s2 = Vo(e3.b0s, e3.b0i, r2), l2 = Vo(e3.b1s, e3.b1i, r2);
            return Math.min(n2, o2, a2, i2, s2, l2);
          }
          var Ko = new At({ id: "hsluv", name: "HSLuv", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 100], name: "Saturation" }, l: { range: [0, 100], name: "Lightness" } }, base: Lo, gamutSpace: Cn, fromBase(e3) {
            let t3, [r2, n2, o2] = [st(e3[0]), st(e3[1]), st(e3[2])];
            return r2 > 99.9999999 ? (t3 = 0, r2 = 100) : r2 < 1e-8 ? (t3 = 0, r2 = 0) : t3 = n2 / Xo(Jo(r2), o2) * 100, [o2, t3, r2];
          }, toBase(e3) {
            let t3, [r2, n2, o2] = [st(e3[0]), st(e3[1]), st(e3[2])];
            return o2 > 99.9999999 ? (o2 = 100, t3 = 0) : o2 < 1e-8 ? (o2 = 0, t3 = 0) : t3 = Xo(Jo(o2), r2) / 100 * n2, [o2, t3, r2];
          }, formats: { color: { id: "--hsluv", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } });
          function Zo(e3, t3) {
            return Math.abs(t3) / Math.sqrt(Math.pow(e3, 2) + 1);
          }
          function Qo(e3) {
            let t3 = Zo(e3.r0s, e3.r0i), r2 = Zo(e3.r1s, e3.r1i), n2 = Zo(e3.g0s, e3.g0i), o2 = Zo(e3.g1s, e3.g1i), a2 = Zo(e3.b0s, e3.b0i), i2 = Zo(e3.b1s, e3.b1i);
            return Math.min(t3, r2, n2, o2, a2, i2);
          }
          kn[0][0], kn[0][1], kn[0][2], kn[1][0], kn[1][1], kn[1][2], kn[2][0], kn[2][1], kn[2][2];
          var ea = new At({ id: "hpluv", name: "HPLuv", coords: { h: { refRange: [0, 360], type: "angle", name: "Hue" }, s: { range: [0, 100], name: "Saturation" }, l: { range: [0, 100], name: "Lightness" } }, base: Lo, gamutSpace: "self", fromBase(e3) {
            let t3, [r2, n2, o2] = [st(e3[0]), st(e3[1]), st(e3[2])];
            return r2 > 99.9999999 ? (t3 = 0, r2 = 100) : r2 < 1e-8 ? (t3 = 0, r2 = 0) : t3 = n2 / Qo(Jo(r2)) * 100, [o2, t3, r2];
          }, toBase(e3) {
            let t3, [r2, n2, o2] = [st(e3[0]), st(e3[1]), st(e3[2])];
            return o2 > 99.9999999 ? (o2 = 100, t3 = 0) : o2 < 1e-8 ? (o2 = 0, t3 = 0) : t3 = Qo(Jo(o2)) / 100 * n2, [o2, t3, r2];
          }, formats: { color: { id: "--hpluv", coords: ["<number> | <angle>", "<percentage> | <number>", "<percentage> | <number>"] } } }), ta = new Pt({ id: "rec2100-linear", name: "Linear REC.2100", white: "D65", toBase: yn.toBase, fromBase: yn.fromBase });
          const ra = 2610 / 16384, na = 16384 / 2610, oa = 32 / 2523, aa = 0.8359375, ia = 2413 / 128, sa = 18.6875;
          var la = new Pt({ id: "rec2100pq", cssId: "rec2100-pq", name: "REC.2100-PQ", base: ta, toBase: (e3) => e3.map(function(e4) {
            return 1e4 * (Math.max(e4 ** oa - aa, 0) / (ia - sa * e4 ** oa)) ** na / 203;
          }), fromBase: (e3) => e3.map(function(e4) {
            let t3 = Math.max(203 * e4 / 1e4, 0);
            return ((aa + ia * t3 ** ra) / (1 + sa * t3 ** ra)) ** 78.84375;
          }) });
          const ca = 0.17883277, ua = 0.28466892, ha = 0.55991073, fa = 3.7743;
          var pa = new Pt({ id: "rec2100hlg", cssId: "rec2100-hlg", name: "REC.2100-HLG", referred: "scene", base: ta, toBase: (e3) => e3.map(function(e4) {
            return e4 <= 0.5 ? e4 ** 2 / 3 * fa : (Math.exp((e4 - ha) / ca) + ua) / 12 * fa;
          }), fromBase: (e3) => e3.map(function(e4) {
            return (e4 /= fa) <= 1 / 12 ? dt(3 * e4, 0.5) : ca * Math.log(12 * e4 - ua) + ha;
          }) });
          const da = {};
          function ga({ id: e3, toCone_M: t3, fromCone_M: r2 }) {
            da[e3] = arguments[0];
          }
          function ma(e3, t3, r2 = "Bradford") {
            let n2 = da[r2], [o2, a2, i2] = et(n2.toCone_M, e3), [s2, l2, c2] = et(n2.toCone_M, t3), u2 = et([[s2 / o2, 0, 0], [0, l2 / a2, 0], [0, 0, c2 / i2]], n2.toCone_M);
            return et(n2.fromCone_M, u2);
          }
          wt.add("chromatic-adaptation-start", (e3) => {
            e3.options.method && (e3.M = ma(e3.W1, e3.W2, e3.options.method));
          }), wt.add("chromatic-adaptation-end", (e3) => {
            e3.M || (e3.M = ma(e3.W1, e3.W2, e3.options.method));
          }), ga({ id: "von Kries", toCone_M: [[0.40024, 0.7076, -0.08081], [-0.2263, 1.16532, 0.0457], [0, 0, 0.91822]], fromCone_M: [[1.8599363874558397, -1.1293816185800916, 0.21989740959619328], [0.3611914362417676, 0.6388124632850422, -6370596838649899e-21], [0, 0, 1.0890636230968613]] }), ga({ id: "Bradford", toCone_M: [[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]], fromCone_M: [[0.9869929054667121, -0.14705425642099013, 0.15996265166373122], [0.4323052697233945, 0.5183602715367774, 0.049291228212855594], [-0.00852866457517732, 0.04004282165408486, 0.96848669578755]] }), ga({ id: "CAT02", toCone_M: [[0.7328, 0.4296, -0.1624], [-0.7036, 1.6975, 61e-4], [3e-3, 0.0136, 0.9834]], fromCone_M: [[1.0961238208355142, -0.27886900021828726, 0.18274517938277307], [0.4543690419753592, 0.4735331543074117, 0.07209780371722911], [-0.009627608738429355, -0.00569803121611342, 1.0153256399545427]] }), ga({ id: "CAT16", toCone_M: [[0.401288, 0.650173, -0.051461], [-0.250268, 1.204414, 0.045854], [-2079e-6, 0.048952, 0.953127]], fromCone_M: [[1.862067855087233, -1.0112546305316845, 0.14918677544445172], [0.3875265432361372, 0.6214474419314753, -0.008973985167612521], [-0.01584149884933386, -0.03412293802851557, 1.0499644368778496]] }), Object.assign(St, { A: [1.0985, 1, 0.35585], C: [0.98074, 1, 1.18232], D55: [0.95682, 1, 0.92149], D75: [0.94972, 1, 1.22638], E: [1, 1, 1], F2: [0.99186, 1, 0.67393], F7: [0.95041, 1, 1.08747], F11: [1.00962, 1, 0.6435] }), St.ACES = [0.32168 / 0.33767, 1, 0.34065 / 0.33767];
          var ba = new Pt({ id: "acescg", cssId: "--acescg", name: "ACEScg", coords: { r: { range: [0, 65504], name: "Red" }, g: { range: [0, 65504], name: "Green" }, b: { range: [0, 65504], name: "Blue" } }, referred: "scene", white: St.ACES, toXYZ_M: [[0.6624541811085053, 0.13400420645643313, 0.1561876870049078], [0.27222871678091454, 0.6740817658111484, 0.05368951740793705], [-0.005574649490394108, 0.004060733528982826, 1.0103391003129971]], fromXYZ_M: [[1.6410233796943257, -0.32480329418479, -0.23642469523761225], [-0.6636628587229829, 1.6153315916573379, 0.016756347685530137], [0.011721894328375376, -0.008284441996237409, 0.9883948585390215]] });
          const ya = 2 ** -16, wa = -0.35828683, va = (Math.log2(65504) + 9.72) / 17.52;
          var ka = new Pt({ id: "acescc", cssId: "--acescc", name: "ACEScc", coords: { r: { range: [wa, va], name: "Red" }, g: { range: [wa, va], name: "Green" }, b: { range: [wa, va], name: "Blue" } }, referred: "scene", base: ba, toBase: (e3) => e3.map(function(e4) {
            return e4 <= -0.3013698630136986 ? 2 * (2 ** (17.52 * e4 - 9.72) - ya) : e4 < va ? 2 ** (17.52 * e4 - 9.72) : 65504;
          }), fromBase: (e3) => e3.map(function(e4) {
            return e4 <= 0 ? (Math.log2(ya) + 9.72) / 17.52 : e4 < ya ? (Math.log2(ya + 0.5 * e4) + 9.72) / 17.52 : (Math.log2(e4) + 9.72) / 17.52;
          }) }), _a = Object.freeze({ __proto__: null, A98RGB: oo, A98RGB_Linear: no, ACEScc: ka, ACEScg: ba, CAM16_JMh: tn, HCT: ln, HPLuv: ea, HSL: eo, HSLuv: Ko, HSV: to, HWB: ro, ICTCP: Ir, JzCzHz: Or, Jzazbz: xr, LCH: Vt, LCHuv: Lo, Lab: Gt, Lab_D65: In, Luv: No, OKLCH: ho, OKLab: ar, OKLrCH: Oo, OKLrab: xo, Okhsl: Co, Okhsv: jo, P3: xn, P3_Linear: vn, ProPhoto: so, ProPhoto_Linear: ao, REC_2020: wn, REC_2020_Linear: yn, REC_2020_Scene_Referred: uo, REC_2100_HLG: pa, REC_2100_Linear: ta, REC_2100_PQ: la, XYZ_ABS_D65: hr, XYZ_D50: $t, XYZ_D65: Bt, sRGB: Cn, sRGB_Linear: _n });
          class Ma {
            constructor(...e3) {
              let t3, r2, n2, o2;
              if (1 === e3.length) {
                let r3 = {};
                "object" == typeof e3[0] && Object.getPrototypeOf(e3[0]).constructor === Object && (e3[0] = __spreadValues({}, e3[0])), t3 = Rt(e3[0], { parseMeta: r3 }), r3.format && (this.parseMeta = r3);
              }
              t3 ? (r2 = t3.space || t3.spaceId, n2 = t3.coords, o2 = t3.alpha) : [r2, n2, o2] = e3, Object.defineProperty(this, "space", { value: At.get(r2), writable: false, enumerable: true, configurable: true }), this.coords = n2 ? n2.slice() : [0, 0, 0], this.alpha = it(o2) ? o2 : void 0 === o2 ? 1 : ft(0, o2, 1);
              for (let e4 in this.space.coords) Object.defineProperty(this, e4, { get: () => this.get(e4), set: (t4) => this.set(e4, t4) });
            }
            get spaceId() {
              return this.space.id;
            }
            clone() {
              return new Ma(this.space, this.coords, this.alpha);
            }
            toJSON() {
              return { spaceId: this.spaceId, coords: this.coords, alpha: this.alpha };
            }
            display(...e3) {
              let t3 = function(e4, _a3 = {}) {
                var _b2 = _a3, { space: t4 = vt.display_space } = _b2, r2 = __objRest(_b2, ["space"]);
                let n2 = bn(e4 = Rt(e4), r2);
                if ("undefined" == typeof CSS || CSS.supports("color", n2) || !vt.display_space) n2 = new String(n2), n2.color = e4;
                else {
                  let o2 = e4;
                  if ((e4.coords.some(it) || it(e4.alpha)) && !(On != null ? On : On = CSS.supports("color", "hsl(none 50% 50%)")) && (o2 = lr(e4), o2.coords = o2.coords.map(st), o2.alpha = st(o2.alpha), n2 = bn(o2, r2), CSS.supports("color", n2))) return n2 = new String(n2), n2.color = o2, n2;
                  o2 = mn(o2, t4), n2 = new String(bn(o2, r2)), n2.color = o2;
                }
                return n2;
              }(this, ...e3);
              return t3.color = new Ma(t3.color), t3;
            }
            static get(e3, ...t3) {
              return bt(e3, this) ? e3 : new Ma(e3, ...t3);
            }
            static try(e3, t3) {
              if (bt(e3, this)) return e3;
              let r2 = Nt(e3, t3);
              return r2 ? new Ma(r2) : null;
            }
            static defineFunction(e3, t3, r2 = t3) {
              let { instance: n2 = true, returns: o2 } = r2, a2 = function(...e4) {
                let r3 = t3(...e4);
                if ("color" === o2) r3 = Ma.get(r3);
                else if ("function<color>" === o2) {
                  let e5 = r3;
                  r3 = function(...t4) {
                    let r4 = e5(...t4);
                    return Ma.get(r4);
                  }, Object.assign(r3, e5);
                } else "array<color>" === o2 && (r3 = r3.map((e5) => Ma.get(e5)));
                return r3;
              };
              e3 in Ma || (Ma[e3] = a2), n2 && (Ma.prototype[e3] = function(...e4) {
                return a2(this, ...e4);
              });
            }
            static defineFunctions(e3) {
              for (let t3 in e3) Ma.defineFunction(t3, e3[t3], e3[t3]);
            }
            static extend(e3) {
              if (e3.register) e3.register(Ma);
              else for (let t3 in e3) Ma.defineFunction(t3, e3[t3]);
            }
          }
          Ma.defineFunctions({ get: Dt, getAll: Lt, set: It, setAll: Ft, to: mn, equals: function(e3, t3) {
            return e3 = Rt(e3), t3 = Rt(t3), e3.space === t3.space && e3.alpha === t3.alpha && e3.coords.every((e4, r2) => e4 === t3.coords[r2]);
          }, inGamut: sr, toGamut: dn, distance: cr, deltas: function(e3, t3, { space: r2, hue: n2 = "shorter" } = {}) {
            e3 = Rt(e3), r2 || (r2 = e3.space), r2 = At.get(r2);
            let o2 = Object.values(r2.coords);
            [e3, t3] = [e3, t3].map((e4) => mn(e4, r2));
            let [a2, i2] = [e3, t3].map((e4) => e4.coords), s2 = a2.map((e4, t4) => {
              let r3 = o2[t4], a3 = i2[t4];
              return "angle" === r3.type && ([e4, a3] = Ut(n2, [e4, a3])), jn(e4, a3);
            }), l2 = jn(e3.alpha, t3.alpha);
            return { space: r2, coords: s2, alpha: l2 };
          }, toString: bn }), Object.assign(Ma, { util: yt, hooks: wt, WHITES: St, Space: At, spaces: At.registry, parse: xt, defaults: vt });
          for (let e3 of Object.keys(_a)) At.register(_a[e3]);
          for (let e3 in At.registry) Sa(e3, At.registry[e3]);
          function Sa(e3, t3) {
            let r2 = e3.replace(/-/g, "_");
            Object.defineProperty(Ma.prototype, r2, { get() {
              let r3 = this.getAll(e3);
              if ("undefined" == typeof Proxy) return r3;
              let n2 = new Proxy(r3, { has: (e4, r4) => {
                try {
                  return At.resolveCoord([t3, r4]), true;
                } catch (e5) {
                }
                return Reflect.has(e4, r4);
              }, get: (e4, r4, o2) => {
                if (r4 && "symbol" != typeof r4 && !(r4 in e4) && r4 in n2) {
                  let { index: n3 } = At.resolveCoord([t3, r4]);
                  if (n3 >= 0) return e4[n3];
                }
                return Reflect.get(e4, r4, o2);
              }, set: (r4, n3, o2, a2) => {
                if (n3 && "symbol" != typeof n3 && !(n3 in r4) || Number(n3) >= 0) {
                  let { index: a3 } = At.resolveCoord([t3, n3]);
                  if (a3 >= 0) return r4[a3] = o2, this.setAll(e3, r4), true;
                }
                return Reflect.set(r4, n3, o2, a2);
              } });
              return n2;
            }, set(t4) {
              this.setAll(e3, t4);
            }, configurable: true, enumerable: true });
          }
          wt.add("colorspace-init-end", (e3) => {
            var _a3;
            Sa(e3.id, e3), (_a3 = e3.aliases) == null ? void 0 : _a3.forEach((t3) => {
              Sa(t3, e3);
            });
          }), Ma.extend(fn), Ma.extend({ deltaE: Gn }), Object.assign(Ma, { deltaEMethods: fn }), Ma.extend(Vn), Ma.extend({ contrast: function(e3, t3, r2) {
            nt(r2) && (r2 = { algorithm: r2 });
            let _a3 = r2 || {}, { algorithm: n2 } = _a3, o2 = __objRest(_a3, ["algorithm"]);
            if (!n2) {
              let e4 = Object.keys(zn).map((e5) => e5.replace(/^contrast/, "")).join(", ");
              throw new TypeError(`contrast() function needs a contrast algorithm. Please specify one of: ${e4}`);
            }
            e3 = Rt(e3), t3 = Rt(t3);
            for (let r3 in zn) if ("contrast" + n2.toLowerCase() === r3.toLowerCase()) return zn[r3](e3, t3, o2);
            throw new TypeError(`Unknown contrast algorithm: ${n2}`);
          } }), Ma.extend(Wn), Ma.extend(Tn), Ma.extend(Qn), Ma.extend(zn);
          const Ea = __spreadProps(__spreadValues({}, le), { windowtext: [0, 0, 0], transparent: [255, 255, 255, 0] }), Ca = new RegExp(Object.keys(Ea).map((e3) => `\\b${e3}\\b`).join("|"), "ig"), xa = (e3) => {
            const t3 = e3.object();
            return t3.a = t3.alpha || 1, delete t3.alpha, t3;
          }, Oa = (e3) => (e3.alpha = e3.a, delete e3.a, ja(e3)), ja = (e3) => {
            if (!e3) return null;
            let t3 = null;
            try {
              t3 = e3 instanceof ie ? e3 : ie(e3);
            } catch (r2) {
              try {
                t3 = ja(new Ma(e3).to("srgb").toString());
              } catch (t4) {
                console.log(`ignore the invalid color: \`${e3}\`, err1: ${r2}, err2: ${t4}`);
              }
            }
            return t3;
          }, Ra = (e3, t3 = false) => e3.replace(v, "").replace(Ca, (e4) => {
            if (!t3 && "transparent" === e4) return e4;
            const r2 = Ea[e4.toLowerCase()];
            return `${r2.length > 3 ? "rgba" : "rgb"}(${r2.toString()})`;
          }), Aa = (e3) => {
            const t3 = Ra(e3);
            return M.test(t3) ? t3 : "";
          }, Ta = (t3, r2 = "normal") => {
            if ("[object Array]" !== Object.prototype.toString.call(t3)) return null;
            const n2 = t3.filter((e3) => !!e3);
            if (n2.length < 1) return null;
            if (1 === n2.length) return ja(n2[0]);
            let o2 = ja(n2.shift() || null), a2 = ja(n2.shift() || null);
            for (; a2; ) {
              if (!o2 && a2) o2 = a2;
              else if (o2 || a2) o2 && a2 && (o2 = "mix" === r2 ? o2.mix(a2, a2.alpha()) : Oa(e2[r2](xa(o2), xa(a2))));
              else {
                if (0 === n2.length) break;
                o2 = ja(n2.shift() || null);
              }
              if (0 === n2.length) break;
              a2 = ja(n2.shift() || null);
            }
            return o2 || null;
          }, Ba = (e3, t3, r2) => {
            const n2 = ja(e3);
            if (!n2) return null;
            const o2 = n2.rgb().array().slice(0, 3), a2 = "[object Array]" === Object.prototype.toString.call(t3) ? Ta(t3) : ja(t3);
            if (!a2) return null;
            const i2 = a2.rgb().array().slice(0, 3), s2 = a2.alpha();
            return ja(`rgba(${o2.map((e4, t4) => Math.round(e4 + s2 * (1 - r2) * (e4 - i2[t4]) / r2)).join(", ")}, ${r2})`);
          }, Pa = (e3) => (299 * e3[0] + 587 * e3[1] + 114 * e3[2]) / 1e3, Na = (e3, t3) => {
            const r2 = (e3 = Math.max(e3, 0)) / (Pa(t3) || 1);
            let n2 = Math.min(255, t3[0] * r2), o2 = Math.min(255, t3[1] * r2), a2 = Math.min(255, t3[2] * r2);
            return 0 === o2 || 255 === n2 || 255 === a2 ? o2 = (1e3 * e3 - 299 * n2 - 114 * a2) / 587 : 0 === n2 ? n2 = (1e3 * e3 - 587 * o2 - 114 * a2) / 299 : 0 !== a2 && 255 !== o2 || (a2 = (1e3 * e3 - 299 * n2 - 587 * o2) / 114), ie.rgb(n2, o2, a2, t3[3] || 1);
          }, La = { hasInit: false, begin: null, showFirstPage: null, error: null, mode: "", whitelist: { tagName: ["MPCPS", "IFRAME"], attribute: [] }, needJudgeFirstPage: true, delayBgJudge: false, noEmit: false, container: null, cssSelectorsPrefix: "", defaultLightWebviewColor: "#fff", defaultLightBgColor: "#fff", defaultLightTextColor: "#191919", defaultDarkWebviewColor: "#191919", defaultDarkBgColor: "#191919", defaultDarkTextColor: "rgba(255,255,255,0.6)", getStyle: null, setStyle: null, getClass: null, setClass: null, getAttr: null, setAttr: null, set(e3, t3, r2) {
            const n2 = t3[r2];
            switch (e3) {
              case "boolean":
                "boolean" == typeof n2 && (this[r2] = n2);
                break;
              case "string":
                "string" == typeof n2 && "" !== n2 && (this[r2] = n2);
                break;
              case "function":
                "function" == typeof n2 && (this[r2] = n2);
                break;
              case "dom":
                n2 instanceof HTMLElement && (this[r2] = n2);
            }
          }, setDefaultColor(e3) {
            this.set("string", e3, "defaultLightWebviewColor"), this.set("string", e3, "defaultDarkWebviewColor");
            const t3 = Ta([this.defaultLightWebviewColor, e3.defaultLightBgColor || this.defaultLightBgColor]);
            t3 && (this.defaultLightBgColor = t3.hex());
            const r2 = Ta([this.defaultDarkWebviewColor, e3.defaultDarkBgColor || this.defaultDarkBgColor]);
            r2 && (this.defaultDarkBgColor = r2.hex());
            const n2 = Ta([this.defaultLightWebviewColor, this.defaultLightBgColor, e3.defaultLightTextColor || this.defaultLightTextColor]);
            n2 && (this.defaultLightTextColor = n2.hex());
            const o2 = Ta([this.defaultDarkWebviewColor, this.defaultDarkBgColor, e3.defaultDarkTextColor || this.defaultDarkTextColor]);
            o2 && (this.defaultDarkTextColor = o2.hex());
          }, reset() {
            this.hasInit = false, Object.assign(this, { begin: null, showFirstPage: null, error: null, mode: "", whitelist: { tagName: ["MPCPS", "IFRAME"], attribute: [] }, needJudgeFirstPage: true, delayBgJudge: false, noEmit: false, container: null, cssSelectorsPrefix: "", defaultLightWebviewColor: "#fff", defaultLightBgColor: "#fff", defaultLightTextColor: "#191919", defaultDarkWebviewColor: "#191919", defaultDarkBgColor: "#191919", defaultDarkTextColor: "rgba(255,255,255,0.6)", getStyle: null, setStyle: null, getClass: null, setClass: null, getAttr: null, setAttr: null });
          } }, Da = (e3) => e3.replace(/^[\s\uFEFF\xA0]+|[\s\uFEFF\xA0]+$/g, ""), Fa = (e3, t3) => null === La.getStyle ? e3.style[t3] : La.getStyle(e3, t3), Ia = (e3, t3) => {
            null === La.setStyle ? Object.assign(e3.style, t3) : La.setStyle(e3, t3);
          };
          function $a(e3, t3 = false) {
            var _a3;
            const r2 = null === La.getClass ? ((_a3 = e3.classList) == null ? void 0 : _a3.toString()) || "" : La.getClass(e3);
            return t3 ? r2.split(/\s+/) : r2;
          }
          const za = (e3, t3) => $a(e3, true).filter((e4) => e4 && e4 !== t3), qa = (e3, t3) => {
            null === La.setClass ? e3.classList.add(t3) : La.setClass(e3, [...za(e3, t3), t3].join(" "));
          }, Ha = (e3, t3) => {
            null === La.setClass ? e3.classList.remove(t3) : La.setClass(e3, za(e3, t3).join(" "));
          }, Wa = (e3, t3) => null === La.getAttr ? e3[t3] : La.getAttr(e3, t3), Ga = (e3, t3, r2) => {
            null === La.setAttr ? e3[t3] = r2 : La.setAttr(e3, t3, r2);
          }, Ya = (e3, t3) => {
            null === La.setAttr ? delete e3[t3] : La.setAttr(e3, t3, null);
          }, Ua = La;
          class Va {
          }
          let Ja, Xa, Ka, Za, Qa = function(e3) {
            return e3.BEFORE_CONVERT_NODE = "beforeConvertNode", e3.AFTER_CONVERT_TEXT_COLOR = "afterConvertTextColor", e3.AFTER_CONVERT_NODE = "afterConvertNode", e3.BEFORE_CONVERT_NODE_BY_UPDATE_STYLE = "beforeConvertNodeByUpdateStyle", e3.AFTER_CONVERT_TEXT_COLOR_BY_UPDATE_STYLE = "afterConvertTextColorByUpdateStyle", e3.AFTER_CONVERT_NODE_BY_UPDATE_STYLE = "afterConvertNodeByUpdateStyle", e3.BEFORE_CONVERT_NODE_BY_RESET = "beforeConvertNodeByReset", e3.AFTER_CONVERT_TEXT_COLOR_BY_RESET = "afterConvertTextColorByReset", e3.AFTER_CONVERT_NODE_BY_RESET = "afterConvertNodeByReset", e3;
          }({});
          function ei(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          let ti, ri, ni = [], oi = [];
          class ai extends Va {
            constructor() {
              super();
            }
            get loopTimes() {
              return di.loopTimes;
            }
            get isDarkmode() {
              return wi.isDarkmode;
            }
            addCss(e3, t3, r2 = true) {
              (r2 ? ni : oi).push(bi.genCss(e3, t3.map(({ key: e4, value: t4 }) => bi.genCssKV(e4, t4)).join("")));
            }
          }
          function ii(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          function si(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          function li(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          Ja = C.FIRST_PAGE_STYLE, Xa = C.OTHER_PAGE_STYLE, Ka = C.FIRST_PAGE_STYLE_NO_MQ, Za = C.OTHER_PAGE_STYLE_NO_MQ;
          var ci = function(e3) {
            return e3.FIRST_PAGE_STYLE = "_firstPageStyle", e3.OTHER_PAGE_STYLE = "_otherPageStyle", e3;
          }(ci || {});
          ti = ci.FIRST_PAGE_STYLE, ri = ci.OTHER_PAGE_STYLE;
          function ui(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          function hi(e3, t3 = false) {
            return (t3 ? [] : [e3]).concat(Array.from(e3.querySelectorAll("*")));
          }
          const fi = { "ue-table-interlace-color-single": "#fcfcfc", "ue-table-interlace-color-double": "#f7faff" };
          function pi(e3, t3, r2) {
            return (t3 = function(e4) {
              var t4 = function(e5) {
                if ("object" != typeof e5 || !e5) return e5;
                var t5 = e5[Symbol.toPrimitive];
                if (void 0 !== t5) {
                  var r3 = t5.call(e5, "string");
                  if ("object" != typeof r3) return r3;
                  throw new TypeError("@@toPrimitive must return a primitive value.");
                }
                return String(e5);
              }(e4);
              return "symbol" == typeof t4 ? t4 : t4 + "";
            }(t3)) in e3 ? Object.defineProperty(e3, t3, { value: r2, enumerable: true, configurable: true, writable: true }) : e3[t3] = r2, e3;
          }
          const di = new class {
            constructor() {
              ei(this, "_plugins", []), ei(this, "length", 0), ei(this, "loopTimes", 0), ei(this, Ja, ""), ei(this, Xa, ""), ei(this, Ka, ""), ei(this, Za, "");
            }
            extend(e3) {
              this._plugins.push(new (e3(ai))()), this.length++;
            }
            emit(e3, ...t3) {
              this._plugins.forEach((r2) => {
                var _a3;
                (_a3 = r2[e3]) == null ? void 0 : _a3.call(r2, ...t3);
              });
            }
            addCss(e3 = false) {
              e3 ? (this[C.FIRST_PAGE_STYLE] += ni.join(""), this[C.FIRST_PAGE_STYLE_NO_MQ] += oi.join("")) : (this[C.OTHER_PAGE_STYLE] += ni.join(""), this[C.OTHER_PAGE_STYLE_NO_MQ] += oi.join(""));
            }
            resetCss() {
              ni = [], oi = [];
            }
            reset() {
              this._plugins = [], this.length = 0, this.loopTimes = 0, this[C.FIRST_PAGE_STYLE] = "", this[C.OTHER_PAGE_STYLE] = "", this[C.FIRST_PAGE_STYLE_NO_MQ] = "", this[C.OTHER_PAGE_STYLE_NO_MQ] = "", this.resetCss();
            }
          }(), gi = new class {
            constructor(e3) {
              ii(this, "_prefix", void 0), ii(this, "_queue", []), ii(this, "_idx", 0), this._prefix = e3;
            }
            get length() {
              return this._queue.length;
            }
            push(e3) {
              const t3 = `${this._prefix}${this._idx++}`;
              qa(e3, t3), this._queue.push({ el: e3, className: t3, updated: !Ua.delayBgJudge });
            }
            forEach(e3) {
              const t3 = [];
              for (this._queue.forEach((r2, n2) => {
                r2.updated && (t3.unshift(n2), e3(r2.el));
              }); t3.length; ) {
                const e4 = t3.shift();
                void 0 !== e4 && this._queue.splice(e4, 1);
              }
            }
            update(e3) {
              this._queue.forEach((t3) => {
                t3.updated || Array.prototype.some.call(e3, (e4) => 1 === e4.nodeType && $a(e4, true).indexOf(t3.className) > -1 && (t3.el = e4, t3.updated = true, true));
              });
            }
            reset() {
              this._queue = [], this._idx = 0;
            }
          }(`${a}text__`), mi = new class {
            constructor(e3) {
              si(this, "classNameReg", void 0), si(this, "_prefix", void 0), si(this, "_stack", []), si(this, "_idx", 0), this._prefix = e3, this.classNameReg = new RegExp(`${this._prefix}\\d+`);
            }
            push(e3, t3, r2) {
              const n2 = `${this._prefix}${this._idx++}`;
              qa(e3, n2), this._stack.unshift({ elOld: e3, el: e3, className: n2, cssKV: t3, updated: !Ua.delayBgJudge, cb: r2 });
            }
            contains(e3, t3) {
              const r2 = e3.getBoundingClientRect(), n2 = [];
              for (this._stack.forEach((e4, t4) => {
                if (e4.updated) {
                  e4.rect || (e4.rect = e4.el.getBoundingClientRect());
                  const o2 = e4.rect;
                  r2.top >= o2.bottom || r2.bottom <= o2.top || r2.left >= o2.right || r2.right <= o2.left || n2.unshift(t4);
                }
              }); n2.length; ) {
                const e4 = n2.shift();
                void 0 !== e4 && t3(this._stack.splice(e4, 1)[0]);
              }
            }
            update(e3) {
              this._stack.forEach((t3) => {
                t3.updated || Array.prototype.some.call(e3, (e4) => 1 === e4.nodeType && $a(e4, true).indexOf(t3.className) > -1 && (t3.el = e4, t3.updated = true, true));
              });
            }
            reset() {
              this._stack = [], this._idx = 0;
            }
          }(`${a}bg__`), bi = new class {
            constructor() {
              li(this, ti, ""), li(this, ri, ""), li(this, "_watcher", {}), li(this, "_styleIdx", 0), li(this, "isFinish", false);
            }
            genCssKV(e3, t3) {
              var _a3, _b2;
              return (_b2 = (_a3 = this._watcher)[e3]) == null ? void 0 : _b2.call(_a3), `${e3}: ${t3} !important;`;
            }
            genCss(e3, t3) {
              return `${"dark" === Ua.mode ? `html.${l} ` : ""}${Ua.cssSelectorsPrefix && `${Ua.cssSelectorsPrefix} `}.${e3}{${t3}}`;
            }
            addCss(e3, t3 = false) {
              this[t3 ? ci.FIRST_PAGE_STYLE : ci.OTHER_PAGE_STYLE] += e3, di.addCss(t3);
            }
            writeStyle(e3 = false) {
              !e3 && wi.isDarkmode && (this.isFinish = true);
              const t3 = [...wi.isDarkmode ? [{ target: this, key: [ci.FIRST_PAGE_STYLE, ci.OTHER_PAGE_STYLE], needMediaQuery: true }] : [], { target: di, key: [C.FIRST_PAGE_STYLE, C.OTHER_PAGE_STYLE], needMediaQuery: true }, { target: di, key: [C.FIRST_PAGE_STYLE_NO_MQ, C.OTHER_PAGE_STYLE_NO_MQ], needMediaQuery: false }].map(({ target: t4, key: [r2, n2], needMediaQuery: a2 }) => {
                let i2 = "";
                return e3 ? (i2 = t4[r2], t4[r2] = "") : (i2 = t4[n2] = t4[r2] + t4[n2], t4[r2] = "", t4[n2] = ""), i2 ? "dark" !== Ua.mode && a2 ? `@media ${o} {${i2}}` : i2 : "";
              }).join("");
              t3 && !Ua.noEmit && document.head.insertAdjacentHTML("beforeend", `<style id="${s}_${this._styleIdx++}" type="text/css">${t3}</style>`);
            }
            watch(e3, t3) {
              this._watcher[e3] = t3;
            }
            unwatch(e3) {
              delete this._watcher[e3];
            }
            reset() {
              var _a3;
              for (let e3 = 0; e3 < this._styleIdx; e3++) {
                const t3 = document.getElementById(`${s}_${e3}`);
                (_a3 = t3 == null ? void 0 : t3.parentNode) == null ? void 0 : _a3.removeChild(t3);
              }
              this.isFinish = false, this._styleIdx = 0;
            }
          }(), yi = new class {
            constructor() {
              ui(this, "_els", []), ui(this, "_firstPageEls", []), ui(this, "_delayEls", []), ui(this, "showFirstPage", false);
            }
            get length() {
              return this._els.length;
            }
            set(e3 = []) {
              this._els = e3;
            }
            get() {
              let e3 = [];
              return this._els.length ? (e3 = this._els, wi.isDarkmode && (this._els = [])) : this._delayEls.length ? (e3 = this._delayEls, this._delayEls = []) : Ua.container && (e3 = Array.from(Ua.container.querySelectorAll("*"))), e3;
            }
            delay() {
              Array.prototype.forEach.call(this._els, (e3) => this._delayEls.push(e3)), this._els = [];
            }
            hasDelay() {
              return !this._els.length && (this._delayEls.length > 0 || null !== Ua.container);
            }
            addFirstPageNode(e3) {
              this._firstPageEls.push(e3);
            }
            showFirstPageNodes() {
              this._firstPageEls.forEach((e3) => {
                !Fa(e3, "visibility") && Ia(e3, { visibility: "visible" });
              }), this.showFirstPage = true;
            }
            emptyFirstPageNodes() {
              this._firstPageEls = [];
            }
            reset() {
              this._els = [], this._firstPageEls = [], this._delayEls = [], this.showFirstPage = false;
            }
          }(), wi = new class {
            constructor() {
              pi(this, "_idx", 0), pi(this, "_defaultDarkTextColorRgb", [0, 0, 0, 0]), pi(this, "_defaultDarkBgColorRgb", [0, 0, 0, 0]), pi(this, "_defaultDarkBgColorHSL", []), pi(this, "_defaultDarkTextColorBrightness", 0), pi(this, "_defaultDarkBgColorBrightness", 0), pi(this, "_defaultDarkBgColorHslBrightness", 0), pi(this, "_maxLimitOffsetBrightness", 0), pi(this, "_inheritTargets", null), pi(this, "isDarkmode", false);
            }
            _inheritNodes(e3) {
              return this._inheritTargets ? this._inheritTargets.filter((t3) => e3.contains(t3)) : hi(e3);
            }
            _adjustBrightness(e3, t3, r2, n2 = false, o2 = false) {
              let a2 = null, i2 = "";
              if (r2.isBgColor) {
                if (e3.alpha() >= 0.05 && Wa(t3, p) && this._inheritNodes(t3).forEach((e4) => {
                  Ya(e4, p);
                }), Wa(t3, g)) {
                  if (Wa(t3, g) === e3.toString() || this.getContrast(Wa(t3, g), e3.toString()) < 1.1) return { newColor: o2 ? e3 : null, extStyle: i2 };
                  this._inheritNodes(t3).forEach((e4) => {
                    Ya(e4, g);
                  });
                }
                const s2 = Wa(t3, u) || Ua.defaultDarkBgColor;
                if (a2 = this.adjustBackgroundBrightness(e3, s2), !r2.hasInlineColor) {
                  const r3 = Ta([s2, a2 || e3]), l2 = ja(Wa(t3, h) || Ua.defaultLightTextColor);
                  if (l2) {
                    const e4 = this._adjustBrightness(l2, t3, { isBgColor: false, isTextShadow: false, isTextColor: true, isBorderColor: false, hasInlineColor: true, parentElementBgColor: r3 }, n2, o2);
                    i2 += bi.genCssKV("color", (e4.newColor || l2).toString()), this._inheritNodes(t3).forEach((t4) => {
                      Ga(t4, c, Ta([r3, e4.newColor || l2])), Ga(t4, h, l2);
                    });
                  }
                }
              } else if (r2.isTextColor || r2.isBorderColor) {
                const i3 = ja(r2.parentElementBgColor || r2.isTextColor && Wa(t3, u) || Ua.defaultDarkBgColor);
                if (i3 && !Wa(t3, p)) {
                  a2 = this.adjustTextBrightness(e3, i3);
                  let r3 = Qa.AFTER_CONVERT_TEXT_COLOR;
                  n2 ? r3 = Qa.AFTER_CONVERT_TEXT_COLOR_BY_UPDATE_STYLE : o2 && (r3 = Qa.AFTER_CONVERT_TEXT_COLOR_BY_RESET), di.emit(r3, t3, { fontColor: a2, bgColor: i3 });
                }
              } else r2.isTextShadow && (Wa(t3, p) || (a2 = this.adjustBackgroundBrightness(e3, Wa(t3, u) || Ua.defaultDarkBgColor)));
              return { newColor: a2 && e3.toString() !== a2.toString() ? a2.rgb() : null, extStyle: i2 };
            }
            _updateBgWithGradient(e3, t3, r2, n2, o2 = false, a2 = false) {
              const i2 = Ta([Wa(t3, u) || Ua.defaultDarkBgColor, e3]), s2 = Ta([Wa(t3, f) || Ua.defaultLightBgColor, e3]);
              this._inheritNodes(t3).forEach((e4) => {
                Ga(e4, u, i2), Ga(e4, f, s2);
              });
              const l2 = n2.slice(-1)[0];
              if (!l2) return "";
              let p2 = null, d2 = b.TEXT_COLOR.indexOf(l2[0]) >= 5;
              if (d2 ? p2 = ja(Ra(l2[1])) : "FONT" === t3.nodeName ? this._try(() => {
                const e4 = t3.getAttribute("color");
                if (e4) {
                  const t4 = ja(e4);
                  t4 && (p2 = t4, d2 = true);
                }
              }) : p2 = ja(Wa(t3, h) || Ua.defaultLightTextColor), null === p2) return "";
              const g2 = this._adjustBrightness(p2, t3, { isBgColor: false, isTextShadow: false, isTextColor: true, isBorderColor: false, hasInlineColor: d2 }, o2, a2), m2 = Ta([i2, g2.newColor || p2]), y2 = p2;
              return this._inheritNodes(t3).forEach((e4) => {
                Ga(e4, c, m2), Ga(e4, h, y2);
              }), g2.newColor ? bi.genCss(r2, bi.genCssKV(l2[0], g2.newColor.toString())) : "";
            }
            _try(e3) {
              var _a3;
              try {
                return e3();
              } catch (e4) {
                console.log("An error occurred when running the dark mode conversion algorithm\n", e4), (_a3 = Ua.error) == null ? void 0 : _a3.call(Ua, e4);
              }
            }
            init() {
              const e3 = ja(Ua.defaultDarkTextColor);
              e3 && (this._defaultDarkTextColorRgb = e3.rgb().array());
              const t3 = ja(Ua.defaultDarkBgColor);
              t3 && (this._defaultDarkBgColorRgb = t3.rgb().array(), this._defaultDarkBgColorHSL = t3.hsl().array()), this._defaultDarkTextColorBrightness = Pa(this._defaultDarkTextColorRgb), this._defaultDarkBgColorBrightness = Pa(this._defaultDarkBgColorRgb), this._defaultDarkBgColorHslBrightness = this._defaultDarkBgColorHSL[2], this._maxLimitOffsetBrightness = Math.max(this._defaultDarkTextColorBrightness - this._defaultDarkBgColorBrightness, 0);
            }
            rebuildAncestorExpando(e3, t3) {
              if (!e3 || !e3.length || !t3) return;
              const r2 = [];
              let n2 = t3;
              for (; n2 && (r2.unshift(n2), n2 !== Ua.container); ) n2 = n2.parentElement;
              const o2 = [...r2, ...e3];
              r2.forEach((e4) => this.convert(e4, [], false, false, true, o2));
            }
            convert(e3, t3 = [], r2 = false, n2 = false, o2 = false, s2) {
              if (this._inheritTargets = s2 || null, !o2) {
                di.resetCss();
                let t4 = Qa.BEFORE_CONVERT_NODE;
                r2 ? t4 = Qa.BEFORE_CONVERT_NODE_BY_UPDATE_STYLE : n2 && (t4 = Qa.BEFORE_CONVERT_NODE_BY_RESET), di.emit(t4, e3);
              }
              let l2 = "", m2 = "";
              if (this.isDarkmode || r2 || n2 || o2) {
                const s3 = e3.nodeName;
                if (Ua.whitelist.tagName.indexOf(s3) > -1) return "";
                if (Ua.whitelist.attribute.some((t4) => e3.hasAttribute(t4))) return "";
                if (0 === t3.length) {
                  const r3 = Fa(e3, "cssText");
                  t3 = (r3 && r3.replace(/("[^;]*);([^;]*")|('[^;]*);([^;]*')/g, "$1$3<$#_SEMICOLON_#$>$2$4").split(";") || []).map((e4) => {
                    const t4 = e4.indexOf(":");
                    return [Da(e4.slice(0, t4).toLowerCase() || ""), Da(e4.slice(t4 + 1).replace(k, ";") || "")];
                  });
                }
                let _2 = false, C2 = false, x2 = false, O2 = "", j2 = "";
                t3 = t3.filter(([e4, t4]) => ("color" === e4 ? _2 = true : /background/i.test(e4) && (C2 = true, "background-position" === e4 ? O2 = t4 : "background-size" === e4 && (j2 = t4)), (/background/i.test(e4) || /^(-webkit-)?border-image/.test(e4)) && E.test(t4) && (x2 = true), y.indexOf(e4) > -1)).sort(([e4], [t4]) => "color" === e4 || "background-image" === e4 && "background-color" === t4 || 0 === t4.indexOf("-webkit-text") ? 1 : -1), w.indexOf(s3) > -1 && !C2 && this._try(() => {
                  let r3 = function(e4) {
                    let t4 = null;
                    return $a(e4, true).some((e5) => !!fi.hasOwnProperty(e5) && (t4 = fi[e5], true)), t4;
                  }(e3);
                  if (r3 || (r3 = e3.getAttribute("bgcolor")), r3) {
                    const e4 = ja(r3);
                    e4 && (t3.unshift(["background-color", e4.toString()]), C2 = true);
                  }
                }), "FONT" !== s3 || _2 || this._try(() => {
                  const r3 = e3.getAttribute("color");
                  if (r3) {
                    const e4 = ja(r3);
                    e4 && (t3.push(["color", e4.toString()]), _2 = true);
                  }
                });
                let R2 = "", A2 = "", T2 = 0;
                t3.some(([e4, t4], r3) => this._try(() => {
                  if (0 !== e4.indexOf("-webkit-text")) return T2 = r3, true;
                  switch (e4) {
                    case "-webkit-text-fill-color":
                      R2 = Aa(t4);
                      break;
                    case "-webkit-text-stroke": {
                      const e5 = t4.split(" ");
                      2 === e5.length && (A2 = Aa(e5[1]));
                      break;
                    }
                    case "-webkit-text-stroke-color":
                      A2 = Aa(t4);
                  }
                  return false;
                })), R2 && (_2 ? t3[t3.length - 1] = ["-webkit-text-fill-color", R2] : (t3.push(["-webkit-text-fill-color", R2]), _2 = true)), T2 && (t3.splice(0, T2), A2 && t3.unshift(["-webkit-text-stroke-color", A2]));
                let B2 = "", P2 = "";
                const N2 = r2 || n2 ? $a(e3) : "";
                if (N2) {
                  let e4 = N2.match(i);
                  e4 && (B2 = e4[0]), e4 = N2.match(mi.classNameReg), e4 && (P2 = e4[0]);
                }
                let L2 = "", D2 = n2;
                D2 && bi.watch("color", () => {
                  D2 = false, bi.unwatch("color");
                }), t3.forEach(([a2, i2]) => this._try(() => {
                  const s4 = i2;
                  let y2 = false;
                  const w2 = b.BG_COLOR.indexOf(a2) > -1, k2 = b.TEXT_SHADOW.indexOf(a2) > -1, R3 = b.TEXT_COLOR.indexOf(a2), A3 = b.BORDER_COLOR.indexOf(a2) > -1, T3 = /gradient/.test(i2), B3 = [];
                  let N3 = "", F2 = null;
                  if (i2 = Ra(i2, T3), M.test(i2)) {
                    if (T3) {
                      let e4 = S.exec(i2);
                      for (; e4; ) B3.push(e4[0]), e4 = S.exec(i2);
                      F2 = Ta(B3, "mix");
                    }
                    let t4 = 0;
                    i2 = i2.replace(S, (o3) => {
                      let a3 = null;
                      if (T3 ? (a3 = F2, y2 = true) : a3 = ja(o3), a3 && a3.alpha() >= 0.05) {
                        const o4 = this._adjustBrightness(a3, e3, { isBgColor: w2, isTextShadow: k2, isTextColor: R3 > -1, isBorderColor: A3, hasInlineColor: _2 }, r2, n2), i3 = !x2 && o4.newColor;
                        if (N3 += o4.extStyle, (w2 || R3 >= 5) && 0 === t4) {
                          const t5 = Ta([Wa(e3, u) || Ua.defaultDarkBgColor, i3 || a3]), r3 = w2 ? Ta([Wa(e3, f) || Ua.defaultLightBgColor, a3]) : a3;
                          this._inheritNodes(e3).forEach((e4) => {
                            w2 ? (Ga(e4, u, t5), Ga(e4, f, r3)) : (Ga(e4, c, t5), Ga(e4, h, r3));
                          });
                        }
                        return i3 && (y2 = true), t4++, (i3 || a3).toString();
                      }
                      return T3 ? null === F2 ? o3 : F2.toString() : o3;
                    }).replace(/\s?!\s?important/gi, "");
                  }
                  if (N3 && (L2 += N3), !(e3 instanceof SVGElement)) {
                    const t4 = /^background/.test(a2), r3 = /^(-webkit-)?border-image/.test(a2);
                    if ((t4 || r3) && E.test(i2)) {
                      y2 = true;
                      const r4 = Wa(e3, f) || Ua.defaultLightBgColor;
                      if (/^(.*?)url\(([^)]*)\)(.*)$/i.test(i2)) {
                        let s5 = "";
                        !Wa(e3, p) && this._inheritNodes(e3).forEach((e4) => {
                          Ga(e4, p, true);
                        }), t4 ? (s5 = bi.genCssKV(a2, `${i2},linear-gradient(${r4}, ${r4})`), O2 && (L2 += bi.genCssKV("background-position", O2), s5 += bi.genCssKV("background-position", `${O2},top left`)), j2 && (L2 += bi.genCssKV("background-size", j2), s5 += bi.genCssKV("background-size", `${j2},100%`)), n2 || (o2 ? this._inheritNodes(e3).forEach((e4) => {
                          Ga(e4, g, r4);
                        }) : P2 ? (m2 += bi.genCss(P2, s5), this._inheritNodes(e3).forEach((e4) => {
                          Ga(e4, g, r4);
                        })) : mi.push(e3, s5, (e4) => {
                          const t5 = [e4.elOld];
                          e4.el !== e4.elOld && t5.push(e4.el), t5.forEach((e5) => {
                            hi(e5).forEach((e6) => {
                              Ga(e6, g, r4);
                            });
                          });
                        }))) : !r4 || C2 || n2 || o2 || (s5 = bi.genCssKV("background-image", `linear-gradient(${r4}, ${r4})`), P2 ? m2 += bi.genCss(P2, s5) : mi.push(e3, s5));
                      }
                      if (!_2) {
                        const t5 = Wa(e3, h) || Ua.defaultLightTextColor;
                        L2 += bi.genCssKV("color", t5), this._inheritNodes(e3).forEach((e4) => {
                          Ga(e4, c, t5);
                        });
                      }
                    }
                  }
                  (y2 || n2) && (!r2 && !n2 && !o2 && v.test(s4) && Ia(e3, { [a2]: s4.replace(v, "") }), T3 ? o2 ? F2 && /^background/.test(a2) && !E.test(i2) && (this._updateBgWithGradient(F2, e3, "", t3, r2, n2), Ga(e3, d, F2)) : n2 || (P2 ? (m2 += bi.genCss(P2, bi.genCssKV(a2, i2)), F2 && /^background/.test(a2) && !E.test(i2) && (l2 += this._updateBgWithGradient(F2, e3, P2, t3, r2, n2))) : mi.push(e3, bi.genCssKV(a2, i2), (o3) => {
                    F2 && /^background/.test(a2) && !E.test(i2) && (l2 += this._updateBgWithGradient(F2, e3, o3.className, t3, r2, n2), Ga(e3, d, F2));
                  })) : ("color" === a2 && (D2 = false, bi.unwatch("color")), L2 += bi.genCssKV(a2, !y2 && n2 ? Fa(e3, a2) : i2)));
                })), D2 && (L2 += bi.genCssKV("color", Fa(e3, "color") || Wa(e3, c) || Ua.defaultDarkTextColor), bi.unwatch("color")), L2 && !o2 && (B2 || (B2 = `${a}${this._idx++}`, qa(e3, B2)), l2 += L2 ? bi.genCss(B2, L2) : ""), l2 += m2, r2 || !function(e4) {
                  return (e4.textContent || "").replace(/\s/g, "").length > 0;
                }(e3) || n2 || o2 || (Ua.delayBgJudge ? gi.push(e3) : mi.contains(e3, (e4) => {
                  var _a3;
                  l2 += bi.genCss(e4.className, e4.cssKV), (_a3 = e4.cb) == null ? void 0 : _a3.call(e4, e4);
                }));
              }
              if (!o2) {
                let t4 = Qa.AFTER_CONVERT_NODE;
                r2 ? t4 = Qa.AFTER_CONVERT_NODE_BY_UPDATE_STYLE : n2 && (t4 = Qa.AFTER_CONVERT_NODE_BY_RESET), di.emit(t4, e3);
              }
              return l2;
            }
            adjustBackgroundBrightness(e3, t3) {
              const r2 = ja(e3);
              if (null === r2) return null;
              const n2 = Ta([t3, r2]);
              if (null === n2) return null;
              const o2 = n2.rgb().array(), a2 = n2.hsl().array(), i2 = Pa(o2);
              let s2 = n2;
              return 0 === a2[1] && a2[2] > 40 || i2 > 250 ? s2 = ie.hsl(0, 0, Math.min(100, 100 + this._defaultDarkBgColorHslBrightness - a2[2]), a2[3] || 1) : i2 > 190 ? s2 = Na(190, o2) : a2[2] < 22 && (a2[2] = 22, s2 = ie.hsl(...a2)), Ba(s2, t3, r2.alpha());
            }
            adjustTextBrightness(e3, t3, r2) {
              const n2 = ja(e3), o2 = ja(t3);
              if (null === n2 || null === o2) return null;
              const a2 = (r2 == null ? void 0 : r2.alpha) || n2.alpha(), i2 = r2 ? n2 : Ta([o2, n2]);
              if (null === i2) return null;
              const s2 = i2.rgb().array(), l2 = i2.hsl().array(), c2 = Pa(s2), u2 = (r2 == null ? void 0 : r2.bgColorPerceivedBrightness) || Pa(o2.rgb().array()), h2 = Math.abs(u2 - c2);
              return c2 >= 250 ? r2 ? Ba(n2, o2, a2) : n2 : h2 > this._maxLimitOffsetBrightness && u2 <= this._defaultDarkBgColorBrightness + 2 ? Ba(Na(this._maxLimitOffsetBrightness + u2, s2), o2, a2) : h2 >= 65 ? r2 ? Ba(n2, o2, a2) : n2 : u2 >= 100 ? l2[2] > 50 ? (l2[2] = 90 - l2[2], this.adjustTextBrightness(ie.hsl(...l2), o2, { alpha: a2, bgColorPerceivedBrightness: u2 })) : Ba(Na(Math.min(this._maxLimitOffsetBrightness, u2 - 65), s2), o2, a2) : l2[2] <= 40 ? (l2[2] = 90 - l2[2], this.adjustTextBrightness(ie.hsl(...l2), o2, { alpha: a2, bgColorPerceivedBrightness: u2 })) : Ba(Na(Math.min(this._maxLimitOffsetBrightness, u2 + 65), s2), o2, a2);
            }
            getContrast(e3, t3) {
              const r2 = ja(e3), n2 = ja(t3);
              return r2 && n2 ? r2.contrast(n2) : 0;
            }
            reset() {
              this._idx = 0, this._defaultDarkTextColorRgb = [0, 0, 0, 0], this._defaultDarkBgColorRgb = [0, 0, 0, 0], this._defaultDarkBgColorHSL = [], this._defaultDarkTextColorBrightness = 0, this._defaultDarkBgColorBrightness = 0, this._defaultDarkBgColorHslBrightness = 0, this._maxLimitOffsetBrightness = 0, this.isDarkmode = false;
            }
          }(), vi = new RegExp(`${a}[^ ]+`, "g");
          let ki = null;
          const _i = (e3, t3 = { type: "dom" }) => {
            var _a3, _b2, _c2;
            if (t3.force && (bi.isFinish = false), !bi.isFinish) try {
              if (Ua.mode) wi.isDarkmode = "dark" === Ua.mode;
              else {
                if (!e3) return;
                wi.isDarkmode = e3.matches;
              }
              "dom" === t3.type ? (wi.isDarkmode && ((_a3 = Ua.begin) == null ? void 0 : _a3.call(Ua, yi.hasDelay())), Array.prototype.forEach.call(yi.get(), (e4) => {
                var _a4;
                if (wi.isDarkmode) {
                  const t4 = $a(e4);
                  t4 && ((e5, t5) => {
                    null === La.setClass ? e5.setAttribute("class", t5) : La.setClass(e5, Da(t5));
                  })(e4, t4.replace(vi, ""));
                }
                if (wi.isDarkmode || di.length) if (Ua.needJudgeFirstPage) {
                  const t4 = e4.getBoundingClientRect(), r2 = t4.top, n2 = t4.bottom;
                  r2 <= 0 && n2 <= 0 ? bi.addCss(wi.convert(e4)) : r2 > 0 && r2 < m || n2 > 0 && n2 < m ? (yi.addFirstPageNode(e4), bi.addCss(wi.convert(e4), true)) : (Ua.needJudgeFirstPage = false, bi.writeStyle(true), yi.showFirstPageNodes(), (_a4 = Ua.showFirstPage) == null ? void 0 : _a4.call(Ua), bi.addCss(wi.convert(e4)));
                } else bi.addCss(wi.convert(e4));
              }), di.loopTimes++) : "bg" === t3.type && wi.isDarkmode && gi.forEach((e4) => mi.contains(e4, (e5) => {
                bi.addCss(bi.genCss(e5.className, e5.cssKV)), "function" == typeof e5.cb && e5.cb(e5);
                const t4 = [e5.elOld];
                e5.elOld !== e5.el && t4.push(e5.el), t4.forEach((e6) => {
                  var _a4, _b3, _c3, _d2, _e2, _f;
                  const t5 = [[c, (_a4 = Wa(e6, c)) != null ? _a4 : null], [u, (_b3 = Wa(e6, u)) != null ? _b3 : null], [h, (_c3 = Wa(e6, h)) != null ? _c3 : null], [f, (_d2 = Wa(e6, f)) != null ? _d2 : null], [p, (_e2 = Wa(e6, p)) != null ? _e2 : null], [g, (_f = Wa(e6, g)) != null ? _f : null]], r2 = hi(e6, true);
                  r2.forEach((e7) => {
                    t5.forEach(([t6, r3]) => {
                      null === r3 ? Ya(e7, t6) : Ga(e7, t6, r3);
                    });
                  }), r2.forEach((e7) => {
                    bi.addCss(wi.convert(e7, void 0, false, true));
                  });
                });
              })), (Ua.needJudgeFirstPage || !Ua.needJudgeFirstPage && !yi.showFirstPage) && ((_b2 = Ua.showFirstPage) == null ? void 0 : _b2.call(Ua)), bi.writeStyle(), yi.emptyFirstPageNodes(), wi.isDarkmode || (Ua.needJudgeFirstPage = false, Ua.delayBgJudge = false, null === Ua.container && "dom" === t3.type && yi.length && yi.delay());
            } catch (e4) {
              console.log("An error occurred when running the dark mode conversion algorithm\n", e4), (_c2 = Ua.error) == null ? void 0 : _c2.call(Ua, e4);
            }
          };
          function Mi(e3, t3 = {}, r2) {
            Si(t3), yi.set(e3), r2 && e3.length && wi.rebuildAncestorExpando(e3, r2), _i(ki, { force: true, type: "dom" });
          }
          function Si(e3 = {}) {
            if (Ua.hasInit) return void console.log("Dark Mode can only be initialized once");
            Ua.hasInit = true;
            const t3 = Ua.whitelist.tagName, r2 = Ua.whitelist.attribute;
            e3.whitelist && (e3.whitelist.tagName instanceof Array && e3.whitelist.tagName.forEach((e4) => {
              e4 = e4.toUpperCase(), -1 === t3.indexOf(e4) && t3.push(e4);
            }), e3.whitelist.attribute instanceof Array && e3.whitelist.attribute.forEach((e4) => {
              -1 === r2.indexOf(e4) && r2.push(e4);
            })), e3.mode && ["dark", "light"].indexOf(e3.mode) > -1 && (Ua.set("string", e3, "mode"), "dark" === e3.mode && qa(document.getElementsByTagName("html")[0], l)), Ua.set("function", e3, "begin"), Ua.set("function", e3, "showFirstPage"), Ua.set("function", e3, "error"), Ua.set("boolean", e3, "needJudgeFirstPage"), Ua.set("boolean", e3, "delayBgJudge"), Ua.set("boolean", e3, "noEmit"), Ua.set("dom", e3, "container"), Ua.set("string", e3, "cssSelectorsPrefix"), Ua.setDefaultColor(e3), Ua.set("function", e3, "getStyle"), Ua.set("function", e3, "setStyle"), Ua.set("function", e3, "getClass"), Ua.set("function", e3, "setClass"), Ua.set("function", e3, "getAttr"), Ua.set("function", e3, "setAttr"), wi.init(), Ua.mode || ki || !window.matchMedia || (ki = window.matchMedia(o), ki.addListener(_i));
          }
          function Ei(e3) {
            yi.set(e3), null !== Ua.container && (mi.update(e3), gi.update(e3)), _i(ki, { force: true, type: "bg" });
          }
          function Ci(e3, t3) {
            bi.isFinish && (bi.addCss(wi.convert(e3, t3 ? Object.keys(t3).map((e4) => [e4, t3[e4]]) : void 0, true)), bi.writeStyle());
          }
          function xi(e3, t3) {
            return wi.getContrast(e3, t3);
          }
          function Oi(e3, t3 = Ua.defaultDarkBgColor) {
            var _a3, _b2;
            return Ua.hasInit ? (_b2 = (_a3 = wi.adjustBackgroundBrightness(e3, t3)) == null ? void 0 : _a3.toString()) != null ? _b2 : null : (console.warn("Dark Mode should be initialized by calling `init()` or `run()` before using `getDmBgColor()`"), null);
          }
          function ji(e3, t3 = Ua.defaultDarkBgColor) {
            var _a3, _b2;
            return Ua.hasInit ? (_b2 = (_a3 = wi.adjustTextBrightness(e3, t3)) == null ? void 0 : _a3.toString()) != null ? _b2 : null : (console.warn("Dark Mode should be initialized by calling `init()` or `run()` before using `getDmFontColor()`"), null);
          }
          function Ri(e3) {
            e3.forEach((e4) => di.extend(e4));
          }
          function Ai(e3) {
            Ua.reset(), di.reset(), gi.reset(), mi.reset(), bi.reset(), yi.reset(), wi.reset(), Ha(document.getElementsByTagName("html")[0], l), ki && (ki.removeListener(_i), ki = null), e3 == null ? void 0 : e3.forEach((e4) => {
              Ya(e4, c), Ya(e4, u), Ya(e4, h), Ya(e4, f), Ya(e4, p), Ya(e4, d), Ya(e4, g);
            });
          }
          function Ti(e3, t3, r2) {
            return function(e4, t4 = {}, r3) {
              const n2 = document.createTreeWalker(e4, NodeFilter.SHOW_ELEMENT, (e5) => e5 instanceof HTMLElement ? "none" === Fa(e5, "display") || E.test(Fa(e5, "backgroundImage") || "") || E.test(Fa(e5, "webkitBorderImage") || Fa(e5, "borderImage") || "") || e5 instanceof SVGElement ? NodeFilter.FILTER_REJECT : (r3 == null ? void 0 : r3(e5)) ? NodeFilter.FILTER_SKIP : NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT), o2 = [];
              for (; n2.nextNode(); ) {
                const e5 = n2.currentNode;
                if (e5 instanceof HTMLElement) {
                  const r4 = (e5.dataset.ignoreDm || "").split(/\s+/);
                  !r4.includes(x.LOW_CONTRAST) && Array.prototype.some.call(e5.childNodes, (e6) => 3 === e6.nodeType && e6.nodeValue.replace(/\s/g, "").length) && wi.getContrast(Wa(e5, c) || Ua.defaultDarkTextColor, Wa(e5, u) || Ua.defaultDarkBgColor) < (t4.minContrast || 1.5) && o2.push({ dom: e5, key: "darkmode-low-contrast", violateRules: "\u6587\u5B57\u4E0E\u80CC\u666F\u8272\u5BF9\u6BD4\u5EA6\u592A\u4F4E\uFF08\u53C2\u8003\u6587\u6863#4.1.1\u4F7F\u7528\u5BF9\u6BD4\u5EA6\u9002\u4E2D\u7684\u989C\u8272\uFF09" }), !r4.includes(x.TEXT_BG_GRADIENT) && Wa(e5, d) && o2.push({ dom: e5, key: "darkmode-no-gradient", violateRules: "\u6587\u5B57\u80CC\u666F\u5C3D\u91CF\u4E0D\u8981\u4F7F\u7528\u6E10\u53D8\uFF08\u53C2\u8003\u6587\u6863#4.1.2\u5982\u975E\u5FC5\u8981\uFF0C\u6587\u5B57\u80CC\u666F\u5C3D\u91CF\u4E0D\u8981\u4F7F\u7528\u6E10\u53D8\uFF09" }), Ua.whitelist.attribute.some((t5) => e5.hasAttribute(t5)) && o2.push({ dom: e5, key: "darkmode-whitelist", violateRules: "\u6CE8\u610F\uFF0C\u6B64\u5904\u5305\u542B\u767D\u540D\u5355\u5C5E\u6027\uFF0C\u4F1A\u8DF3\u8FC7darkmode\u7B97\u6CD5\u8F6C\u6362\uFF08\u53C2\u8003\u6587\u6863#4.5.1 \u6307\u5B9A\u8282\u70B9\u8DF3\u8FC7\u7B97\u6CD5\u8F6C\u6362\uFF09" });
                }
              }
              return o2;
            }(e3, t3, r2);
          }
        })(), n;
      })());
    }
  });

  // engine/index.ts
  var engine_exports = {};
  __export(engine_exports, {
    verifyArticleStructure: () => verifyArticleStructure
  });
  var import_mp_darkmode = __toESM(require_darkmode_min(), 1);

  // engine/paragraph.ts
  var blockEleTagName = ["P", "DIV", "SECTION", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "TABLE", "WX-VIEW"];
  var canNotSplitEleClassName = ["js_product_container", "js_blockquote_wrap"];
  var canNotSplitEleTagName = ["BLOCKQUOTE"];
  var selfTagName = ["HR", "IMG"];
  var noRenderEleTagName = ["STYLE", "SCRIPT", "META", "LINK", "TITLE", "HEAD", "NOSCRIPT", "TEMPLATE"];
  function childNodesHasBlockEle(element, opts) {
    if (!element || element.nodeType !== 1) return false;
    for (let i = 0, len = element.children.length; i < len; i++) {
      if (blockEleTagName.indexOf(element.children[i].tagName) !== -1 || opts.getSpan && element.children[i].tagName === "SPAN" && (childNodesHasBlockEle(element.children[i], opts) || element.children[i].querySelector("br") !== null)) {
        return true;
      }
    }
    return false;
  }
  function isNotSplitEle(ele, opts) {
    for (let i = 0; i < canNotSplitEleClassName.length; i++) {
      if (ele.className.indexOf(canNotSplitEleClassName[i]) > -1) return true;
    }
    if (opts.ignoreFlexChildren && ele.style.display === "flex" && (ele.style.flexDirection === "row" || ele.style.flexDirection === "row-reverse") && ele.children.length > 1 || opts.ignoreNotWriteableChildren && (ele.getAttribute("contenteditable") === "false" || ele.childNodes.length === 1 && ele.childNodes[0].getAttribute("contenteditable") === "false")) {
      return true;
    }
    return canNotSplitEleTagName.indexOf(ele.tagName) > -1;
  }
  function getParaList(element, opts, isRoot = true) {
    const children = element.children;
    if (!children.length) return children;
    let child;
    let paragraphList = [];
    for (let i = 0; i < children.length; i++) {
      child = children[i];
      child.isWrapper = void 0;
      if (noRenderEleTagName.indexOf(child.tagName) !== -1) continue;
      if (opts && opts.isMarkNode && opts.isMarkNode(child)) continue;
      if (childNodesHasBlockEle(child, opts) && !isNotSplitEle(child, opts)) {
        paragraphList = paragraphList.concat(getParaList(child, opts, false));
        if (opts.getNestedStructure && child.tagName !== "SPAN") {
          child.isWrapper = true;
          paragraphList.push(child);
        }
      } else if (opts.getSpan && child.querySelector("br") !== null) {
        let pushed = false;
        Array.prototype.forEach.call(child.querySelectorAll("br"), (br) => {
          let currentNode = br;
          let parentNode = br.parentNode;
          while (parentNode.tagName === "SPAN" && currentNode === parentNode.lastChild) {
            currentNode = parentNode;
            parentNode = parentNode.parentNode;
          }
          if (parentNode.tagName === "SPAN" || parentNode.tagName !== "SPAN" && currentNode !== parentNode.lastChild) {
            paragraphList.push(br);
            pushed = true;
          }
        });
        if (child.tagName !== "SPAN") {
          if (pushed === false) {
            paragraphList.push(child);
          } else if (opts.getNestedStructure) {
            child.isWrapper = true;
            paragraphList.push(child);
          }
        }
      } else if (!opts.getSpan || opts.getSpan && child.tagName !== "SPAN" && selfTagName.indexOf(child.tagName) === -1) {
        paragraphList.push(child);
      }
    }
    if (isRoot) {
      let needExecBr = true;
      for (let i = paragraphList.length - 1, c = paragraphList[i]; i >= 0; i--, c = paragraphList[i]) {
        if (c && c.isWrapper) {
          needExecBr = true;
        } else if (c && needExecBr && c.tagName === "BR") {
          needExecBr = false;
          while (c && !c.isWrapper) {
            if (c.nextElementSibling !== null) {
              paragraphList.splice(i + 1, 0, c.nextElementSibling);
              break;
            } else {
              c = c.parentNode;
            }
          }
        }
      }
    }
    return paragraphList;
  }
  getParaList.paragraphStartIdx = 1e6;
  var paragraph_default = getParaList;

  // engine/dom.ts
  var bookmarkPrefix = "_baidu_bookmark_";
  var checktextTagName = "mpchecktext";
  var checktextTmpTagName = "mptmpchecktext";
  var payFilterTagName = "mp-pay-preview-filter";
  function isMarkNode(node) {
    if (!node || !node.tagName) return false;
    const tagName = node.tagName.toLowerCase();
    if (tagName === checktextTagName || tagName === checktextTmpTagName || tagName === payFilterTagName) {
      return true;
    }
    if (node.nodeType === 1 && node.id && new RegExp("^" + bookmarkPrefix, "i").test(node.id)) {
      return true;
    }
    return false;
  }
  var specialTags = /iframe|video|audio|cps|mp|img|animateTransform|hr|path|br|svg|^g$|^a$/i;
  var domUtils = { isMarkNode, specialTags };
  function isEmptyParagraph(element) {
    const html = element.innerHTML.trim();
    return html === "" || /^(\s*<br[^>]*?\s*\/?>\s*)*$/i.test(html) || /^\s*$/.test(html) || /^<span[^>]*\bleaf\b[^>]*>\s*(<br[^>]*>)?\s*<\/span>$/i.test(html);
  }

  // engine/nest.ts
  var getElementChildren = (node) => {
    if (!node || !node.children) return [];
    const children = node.children;
    if (typeof children.item === "function") return children;
    return children.filter((c) => !!c.tagName);
  };
  var hasOtherSignificantContent = (node, excludeChild) => {
    if (!node) return false;
    if (node.childNodes && typeof node.childNodes.item === "function") {
      for (let i = 0; i < node.childNodes.length; i++) {
        const child = node.childNodes[i];
        if (child === excludeChild) continue;
        if (child.nodeType === 3 && child.textContent && child.textContent.trim()) return true;
        if (child.nodeType === 1) return true;
      }
      return false;
    }
    if (node.children && Array.isArray(node.children)) {
      for (let j = 0; j < node.children.length; j++) {
        const c = node.children[j];
        if (c === excludeChild) continue;
        if (!c.tagName && c.data && c.data.trim()) return true;
        if (c.tagName) return true;
      }
      return false;
    }
    return false;
  };
  function deleteNestNode({ root, isNeedDelete = false, isTest = false }) {
    const MAX_STYLE_LEVEL = 15;
    const hasNestedNode = [];
    const willBeDeletedNodes = [];
    const willBeDeletedSet = /* @__PURE__ */ new Set();
    const pushWillBeDeleted = (node) => {
      if (!node || willBeDeletedSet.has(node)) return false;
      willBeDeletedSet.add(node);
      willBeDeletedNodes.push(node);
      return true;
    };
    const getTag = (node) => (node && node.tagName || "").toLowerCase();
    const getStyle = (node) => {
      if (!node) return "";
      if (node.attrs && typeof node.attrs.style === "string") return node.attrs.style;
      if (typeof node.getAttribute === "function") return node.getAttribute("style") || "";
      return "";
    };
    const depth1 = (node) => {
      if (node === null) return;
      if (node.children) {
        node.level = node.parentNode && node.parentNode.level ? node.parentNode.level + 1 : 1;
        if (node.attrs) node.attrs["data-nest-level"] = String(node.level);
        if (typeof node.setAttribute === "function") node.setAttribute("data-nest-level", String(node.level));
        if (node.level >= MAX_STYLE_LEVEL) {
          hasNestedNode.push(node);
          return;
        }
      }
      const children = getElementChildren(node);
      for (let i = 0; i < children.length; i++) depth1(children[i]);
    };
    root.level = 0;
    depth1(root);
    if (hasNestedNode.length > 0 && (isNeedDelete || isTest)) {
      hasNestedNode.forEach((item) => {
        let deleteLevel = MAX_STYLE_LEVEL - 2;
        let currentNode = item;
        let tagList = [];
        let styleDetailList = [];
        let parentStyleDetailList = [];
        const parentHasTag = (tagName) => {
          let result = true;
          if (!tagList.includes(tagName)) {
            tagList.push(tagName);
            result = false;
          }
          return result;
        };
        const parentHasStyle = (str = "", isParentNode = false) => {
          const allStyle = str.split(";");
          let result = true;
          if (isParentNode) {
            allStyle.forEach((s) => {
              if (!parentStyleDetailList.includes(s)) {
                result = false;
                parentStyleDetailList.push(s);
              }
            });
          } else {
            allStyle.forEach((s) => {
              if (!styleDetailList.includes(s) && !parentStyleDetailList.includes(s)) {
                result = false;
                styleDetailList.push(s);
              }
            });
          }
          return result;
        };
        while (deleteLevel) {
          const grandParent = currentNode.parentNode && currentNode.parentNode.parentNode;
          const gpChildren = grandParent ? getElementChildren(grandParent) : [];
          const gpChildrenLen = gpChildren.length;
          if (currentNode.parentNode && grandParent && gpChildrenLen === 1) {
            const nodeTagName = getTag(currentNode.parentNode);
            const nodeStyle = getStyle(currentNode.parentNode);
            if (!parentHasTag(nodeTagName) || parentHasTag(nodeTagName) && !parentHasStyle(nodeStyle, true)) {
              currentNode = currentNode.parentNode;
            } else {
              if (!domUtils.specialTags.test(nodeTagName)) {
                if (!isTest) {
                  const deletedNode = currentNode.parentNode;
                  if (hasOtherSignificantContent(deletedNode, currentNode)) {
                    currentNode = currentNode.parentNode;
                    deleteLevel -= 1;
                    continue;
                  }
                  const grandParentNode = currentNode.parentNode.parentNode;
                  if (grandParentNode.replaceChild) {
                    grandParentNode.replaceChild(currentNode, deletedNode);
                  } else {
                    currentNode.parentNode = grandParentNode;
                    grandParentNode.children[grandParentNode.children.indexOf(deletedNode)] = currentNode;
                  }
                } else {
                  pushWillBeDeleted(currentNode.parentNode);
                  return;
                }
              }
            }
          }
          deleteLevel -= 1;
        }
        currentNode = item;
        const stack = [currentNode];
        while (stack.length) {
          const downNode = stack.pop();
          if (downNode.isNeedEmpty) {
            tagList = [];
            styleDetailList = [];
          }
          const downChildren = getElementChildren(downNode);
          const downChildrenLen = downChildren.length;
          if (downChildrenLen === 1) {
            const child = downChildren[0];
            const childChildren = getElementChildren(child);
            const childChildrenLen = childChildren.length;
            if (childChildrenLen === 1) {
              const grandChild = childChildren[0];
              const gcChildren = getElementChildren(grandChild);
              const gcChildrenLen = gcChildren.length;
              if (gcChildrenLen > 0) {
                const nodeTagName = getTag(child);
                const nodeStyle = getStyle(child);
                if (!parentHasTag(nodeTagName) || parentHasTag(nodeTagName) && !parentHasStyle(nodeStyle)) {
                  stack.push(child);
                } else {
                  if (!domUtils.specialTags.test(nodeTagName)) {
                    if (!isTest) {
                      if (hasOtherSignificantContent(child, childChildren[0])) {
                        stack.push(child);
                        continue;
                      }
                      const tmp = childChildren[0];
                      if (downNode.replaceChild) {
                        downNode.replaceChild(tmp, child);
                      } else {
                        downNode.children[downNode.children.indexOf(child)] = tmp;
                        tmp.parentNode = downNode;
                      }
                      stack.push(downNode);
                    } else {
                      pushWillBeDeleted(child);
                      return;
                    }
                  }
                }
              }
            } else if (childChildrenLen > 1) {
              for (let i = childChildrenLen - 1; i >= 0; i--) {
                childChildren[i].isNeedEmpty = true;
                stack.push(childChildren[i]);
              }
            }
          } else if (downChildrenLen > 1) {
            for (let i = downChildrenLen - 1; i >= 0; i--) {
              downChildren[i].isNeedEmpty = true;
              stack.push(downChildren[i]);
            }
          }
        }
      });
    }
    if (isTest) return willBeDeletedNodes;
  }

  // engine/rules-text.ts
  var propertyRules = {
    "font-family": "\u5F53\u524D\u5185\u5BB9\u4F7F\u7528\u4E86\u81EA\u5B9A\u4E49\u5B57\u4F53\uFF0C\u79FB\u52A8\u7AEF\u53EF\u80FD\u672A\u9884\u88C5\u8BE5\u5B57\u4F53\uFF0C\u5B9E\u9645\u663E\u793A\u6548\u679C\u53EF\u80FD\u4E0E\u9884\u89C8\u4E0D\u4E00\u81F4\uFF0C\u8BF7\u6838\u5B9E\uFF08\u53C2\u8003\u6587\u6863 #3\u3001\u5B57\u4F53\u4F7F\u7528\u89C4\u8303\uFF09",
    "opacity": "\u8BE5\u56FE\u7247 opacity \u503C\u4E3A 0\uFF08\u5B8C\u5168\u900F\u660E\uFF09\uFF0C\u79FB\u52A8\u7AEF\u53EF\u80FD\u65E0\u6CD5\u6B63\u5E38\u663E\u793A\uFF0C\u4E14\u53D1\u5E03\u540E\u65E0\u6CD5\u901A\u8FC7\u540E\u53F0\u66FF\u6362\uFF0C\u8BF7\u786E\u8BA4\u662F\u5426\u7B26\u5408\u9884\u671F\uFF08\u53C2\u8003\u6587\u6863 #1.1 opacity\uFF09",
    "caret-color": "\u5149\u6807\u989C\u8272\uFF08caret-color\uFF09\u88AB\u8BBE\u7F6E\u4E3A\u900F\u660E\uFF0C\u53EF\u80FD\u5BFC\u81F4\u7F16\u8F91\u65F6\u65E0\u6CD5\u5B9A\u4F4D\u5149\u6807\u4F4D\u7F6E\uFF0C\u8BF7\u786E\u8BA4\u662F\u5426\u7B26\u5408\u9884\u671F\uFF08\u53C2\u8003\u6587\u6863 #1.2 caret-color\uFF09",
    "line-height": "\u5F53\u524D\u5185\u5BB9\u884C\u9AD8\uFF08line-height\uFF09\u8FC7\u5C0F\uFF0C\u591A\u884C\u6587\u672C\u53EF\u80FD\u5B58\u5728\u91CD\u53E0\uFF0C\u8BF7\u6838\u5B9E\u9605\u8BFB\u6548\u679C\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.3 line-height\uFF09",
    "text-align": "\u6587\u672C\u5BF9\u9F50\u5C5E\u6027\u4F7F\u7528\u4E86 start \u6216 end\uFF0C\u4E14\u4E0E\u5916\u5C42\u5BB9\u5668\u7684\u5BF9\u9F50\u65B9\u5F0F\u4E0D\u4E00\u81F4\uFF0C\u4E0D\u540C\u7EC8\u7AEF\u89E3\u6790\u5DEE\u5F02\u4F1A\u5BFC\u81F4\u5BF9\u9F50\u6548\u679C\u4E0D\u7EDF\u4E00\uFF0C\u8BF7\u6838\u5B9E\u5404\u7AEF\u663E\u793A\u662F\u5426\u4E00\u81F4\uFF08\u53C2\u8003\u6587\u6863 #1.6 text-align\uFF09",
    "height": "\u8BE5\u5BB9\u5668 height \u503C\u4E3A 0\uFF0C\u53EF\u80FD\u5BFC\u81F4\u79FB\u52A8\u7AEF\u5185\u5BB9\u663E\u793A\u5F02\u5E38\u6216\u4E0D\u53EF\u89C1\uFF0C\u8BF7\u6838\u5B9E\u662F\u5426\u7B26\u5408\u9884\u671F\uFF08\u53C2\u8003\u6587\u6863 #1.5.1 height:0\uFF09",
    "width": "\u5F53\u524D\u5185\u5BB9\u5B58\u5728\u7279\u6B8A\u6392\u7248\uFF0C\u53EF\u80FD\u5728\u4E0D\u540C\u5C4F\u5E55\u4E0B\u51FA\u73B0\u5C45\u4E2D\u4E0D\u4E00\u81F4\u3001\u5BBD\u5EA6\u5DEE\u5F02\u6216\u6EA2\u51FA\u95EE\u9898\uFF0C\u8BF7\u6838\u5B9E\u663E\u793A\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.4 width\uFF09",
    "animate-begin": "\u8BE5\u52A8\u753B begin \u5305\u542B touchstart \u89E6\u6478\u4E8B\u4EF6\uFF0C\u4F46\u672A\u5305\u542B click \u70B9\u51FB\u4E8B\u4EF6\uFF0CPC \u7AEF\u53EF\u80FD\u65E0\u6CD5\u901A\u8FC7\u9F20\u6807\u89E6\u53D1\u64AD\u653E\uFF0C\u8BF7\u786E\u8BA4\u4EA4\u4E92\u662F\u5426\u7B26\u5408\u9884\u671F\uFF08\u53C2\u8003\u6587\u6863 #1.7 begin\uFF09",
    "height-nodisplay": "\u5185\u5BB9\u5B9E\u9645\u9AD8\u5EA6\u8D85\u51FA\u5BB9\u5668\u8BBE\u5B9A\u7684 height \u9650\u5236\uFF0C\u6EA2\u51FA\u90E8\u5206\u53EF\u80FD\u5728\u79FB\u52A8\u7AEF\u88AB\u88C1\u5207\uFF0C\u8BF7\u6838\u5B9E\u663E\u793A\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.5.2 \u5185\u5BB9\u6EA2\u51FA\u5BB9\u5668\uFF09",
    "line-height-overlapping": "\u884C\u95F4\u8DDD\uFF08line-height\uFF09\u8BBE\u7F6E\u8F83\u5C0F\uFF0C\u591A\u884C\u6587\u672C\u53EF\u80FD\u5B58\u5728\u91CD\u53E0\uFF0C\u8BF7\u6838\u5B9E\u9605\u8BFB\u6548\u679C\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.3 line-height\uFF09",
    "nest-level": "\u5F53\u524D\u5185\u5BB9 DOM \u5D4C\u5957\u5C42\u7EA7\u8F83\u6DF1\uFF0C\u5B58\u5728\u5197\u4F59\u7684\u91CD\u590D\u5D4C\u5957\u7ED3\u6784\uFF0C\u53EF\u80FD\u5F71\u54CD\u6E32\u67D3\u8868\u73B0\uFF0C\u8BF7\u6838\u5B9E\uFF08\u53C2\u8003\u6587\u6863 #2.1 \u5D4C\u5957\u5C42\u7EA7\u9650\u5236\uFF09",
    // Reserved copy: this rule has no spec chapter or CLI implementation yet.
    "redundant-node": "\u5F53\u524D\u5185\u5BB9\u5B58\u5728\u5927\u91CF\u7A7A\u767D\u5B50\u8282\u70B9\uFF08\u5B50\u8282\u70B9\u6570 > 20 \u4E14\u7A7A\u8282\u70B9\u6570 > 15\uFF09\uFF0C\u8FD9\u4E9B\u5197\u4F59\u7A7A\u8282\u70B9\u4F1A\u88AB\u7F16\u8F91\u5668\u81EA\u52A8\u5220\u9664\uFF0C\u8BF7\u6838\u5B9E\u662F\u5426\u7B26\u5408\u9884\u671F",
    "node-leaf": "\u7EC4\u4EF6\u5BB9\u5668\uFF08section[nodeleaf]\uFF09\u5185\u90E8\u7ED3\u6784\u53EF\u80FD\u4E0D\u7B26\u5408\u89C4\u8303\uFF0C\u8BE5\u5BB9\u5668\u4EC5\u5141\u8BB8\u5305\u542B\u5B98\u65B9\u6307\u5B9A\u7684\u7279\u5B9A\u7EC4\u4EF6\u6216 img \u56FE\u7247\u5143\u7D20\uFF0C\u8BF7\u6838\u5B9E\uFF08\u53C2\u8003\u6587\u6863 #2.3 section[nodeleaf] \u8282\u70B9\u89C4\u8303\uFF09",
    "span-leaf": "\u884C\u5185\u5BB9\u5668\uFF08span[leaf]\uFF09\u4E2D\u68C0\u6D4B\u5230\u5757\u7EA7\u5B50\u5143\u7D20\uFF0C\u8BE5\u5BB9\u5668\u4EC5\u5141\u8BB8\u5305\u542B\u6587\u672C\u6216\u884C\u5185\u5143\u7D20\uFF08\u5982 span\u3001strong\u3001\u94FE\u63A5\u53CA\u884C\u5185\u56FE\u7247\u7B49\uFF09\uFF0C\u8BF7\u6838\u5B9E\u7ED3\u6784\u662F\u5426\u6B63\u786E\uFF08\u53C2\u8003\u6587\u6863 #2.2 span[leaf] \u8282\u70B9\u89C4\u8303\uFF09",
    "pre": "\u5F53\u524D pre \u6807\u7B7E\u5185\u7684\u5185\u5BB9\u8D85\u51FA\u5BB9\u5668\u5BBD\u5EA6\uFF0C\u4E14\u672A\u542F\u7528\u6A2A\u5411\u6EDA\u52A8\uFF0C\u79FB\u52A8\u7AEF\u53EF\u80FD\u65E0\u6CD5\u5B8C\u6574\u9605\u8BFB\uFF0C\u8BF7\u6838\u5B9E\u663E\u793A\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.8 pre \u6807\u7B7E\uFF09",
    "darkmode-low-contrast": "\u6587\u5B57\u4E0E\u80CC\u666F\u8272\u5BF9\u6BD4\u5EA6\u592A\u4F4E\uFF08\u53C2\u8003\u6587\u6863#4.1.1\u4F7F\u7528\u5BF9\u6BD4\u5EA6\u9002\u4E2D\u7684\u989C\u8272\uFF09",
    "darkmode-no-gradient": "\u6587\u5B57\u80CC\u666F\u5C3D\u91CF\u4E0D\u8981\u4F7F\u7528\u6E10\u53D8\uFF08\u53C2\u8003\u6587\u6863#4.1.2\u5982\u975E\u5FC5\u8981\uFF0C\u6587\u5B57\u80CC\u666F\u5C3D\u91CF\u4E0D\u8981\u4F7F\u7528\u6E10\u53D8\uFF09"
  };
  var WIDTH_DETAIL_RULES = {
    "\u5C45\u4E2D\u5E03\u5C40\u4E0D\u4E00\u81F4": "\u5F53\u524D\u5143\u7D20\u5728\u4E0D\u540C\u5C4F\u5E55\u5BBD\u5EA6\u4E0B\u5C45\u4E2D\u72B6\u6001\u4E0D\u4E00\u81F4\uFF08\u90E8\u5206\u5C4F\u5E55\u5C45\u4E2D\u3001\u90E8\u5206\u4E0D\u5C45\u4E2D\uFF09\uFF0C\u901A\u5E38\u7531\u56FA\u5B9A px \u5BBD\u5EA6\u6216\u5916\u8FB9\u8DDD\u504F\u79FB\u5F15\u8D77\uFF0C\u79FB\u52A8\u7AEF\u663E\u793A\u6548\u679C\u53EF\u80FD\u4E0E\u7F16\u8F91\u5668\u9884\u89C8\u4E0D\u4E00\u81F4\uFF0C\u8BF7\u6838\u5B9E\uFF08\u53C2\u8003\u6587\u6863 #1.4.1 \u5C45\u4E2D\u5E03\u5C40\u4E0D\u4E00\u81F4\uFF09",
    "\u5B58\u5728\u6EA2\u51FA\u95EE\u9898": "\u5F53\u524D\u5143\u7D20\u5BBD\u5EA6\u8D85\u51FA\u5BB9\u5668\u8FB9\u754C\uFF0C\u79FB\u52A8\u7AEF\u53EF\u80FD\u51FA\u73B0\u6C34\u5E73\u6EDA\u52A8\u6216\u5185\u5BB9\u88AB\u88C1\u5207\uFF0C\u5E38\u89C1\u539F\u56E0\u5305\u62EC\u56FA\u5B9A\u5BBD\u5EA6\u8FC7\u5927\u3001margin/padding \u504F\u79FB\u3001transform \u4F4D\u79FB\u7B49\uFF0C\u8BF7\u6838\u5B9E\u663E\u793A\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.4.2 \u5B58\u5728\u6EA2\u51FA\u95EE\u9898\uFF09",
    "\u4E0D\u540C\u5C4F\u5E55\u4E0B\u5BBD\u5EA6\u5DEE\u5F02": "\u5F53\u524D\u5143\u7D20\u5728\u4E0D\u540C\u5C4F\u5E55\u5BBD\u5EA6\u4E0B\u6E32\u67D3\u5BBD\u5EA6\u5DEE\u5F02\u8F83\u5927\uFF0C\u4E14\u5360\u7236\u5BB9\u5668\u7684\u6BD4\u4F8B\u4E5F\u4E0D\u4E00\u81F4\uFF0C\u901A\u5E38\u7531\u56FA\u5B9A px \u5BBD\u5EA6\u672A\u505A\u54CD\u5E94\u5F0F\u9002\u914D\u5F15\u8D77\uFF0C\u8BF7\u6838\u5B9E\u663E\u793A\u662F\u5426\u6B63\u5E38\uFF08\u53C2\u8003\u6587\u6863 #1.4.3 \u4E0D\u540C\u5C4F\u5E55\u4E0B\u5BBD\u5EA6\u5DEE\u5F02\uFF09"
  };

  // engine/layout.ts
  var DEFAULT_SCREENS = [
    { width: 585, style: { width: "585px" } },
    { width: 677, style: { width: "677px" } },
    { width: 375, style: { width: "375px" } }
  ];
  function removeLayoutSandbox(sandbox) {
    if (!sandbox || typeof sandbox.remove !== "function") {
      return;
    }
    if (sandbox.__debugSandbox) {
      console.log("[LayoutSandbox] \u8C03\u8BD5\u6A21\u5F0F\uFF1Asandbox \u4FDD\u7559\u5728 DOM \u91CC\uFF0C\u4FBF\u4E8E\u6392\u67E5");
      return;
    }
    if (sandbox.__selfDestructTimer) {
      clearTimeout(sandbox.__selfDestructTimer);
      sandbox.__selfDestructTimer = null;
    }
    try {
      if (sandbox.parentNode) {
        sandbox.parentNode.removeChild(sandbox);
      }
    } catch (e) {
    }
  }
  function createLayoutSandbox(htmlString, options) {
    const sandbox = document.createElement("div");
    sandbox.id = "test";
    sandbox.className = "rich_media_content";
    const debugSandbox = (options == null ? void 0 : options.debugSandbox) === true;
    if (debugSandbox) {
      Object.assign(sandbox.style, {
        position: "absolute",
        zIndex: "10000",
        border: "2px dashed red",
        background: "#fff",
        boxSizing: "border-box",
        color: "rgba(0, 0, 0, 0.9)",
        fontSize: "var(--articleFontsize)",
        overflow: "hidden",
        textAlign: "justify"
      });
      sandbox.__debugSandbox = true;
    } else {
      Object.assign(sandbox.style, {
        position: "fixed",
        left: "-9999px",
        top: "-9999px",
        visibility: "hidden",
        pointerEvents: "none",
        zIndex: "-1",
        boxSizing: "border-box",
        color: "rgba(0, 0, 0, 0.9)",
        fontSize: "var(--articleFontsize)",
        overflow: "hidden",
        textAlign: "justify"
      });
      sandbox.__selfDestructTimer = setTimeout(() => {
        if (sandbox.parentNode) {
          console.warn("[LayoutSandbox] \u8D85\u65F6\u81EA\u6BC1\uFF0C\u53EF\u80FD removeLayoutSandbox \u672A\u6B63\u5E38\u6267\u884C");
          sandbox.parentNode.removeChild(sandbox);
        }
      }, 1e4);
    }
    if (!document.getElementById("rich-media-styles")) {
      const style = document.createElement("style");
      style.id = "rich-media-styles";
      style.textContent = `
      .rich_media_content * {
        max-width: 100% !important;
        box-sizing: border-box !important;
        -webkit-box-sizing: border-box !important;
        word-wrap: break-word !important;
      }
    `;
      document.head.appendChild(style);
    }
    document.body.appendChild(sandbox);
    sandbox.innerHTML = htmlString;
    return sandbox;
  }
  function waitForImagesToLoad(sandbox, timeoutMs = 5e3) {
    return __async(this, null, function* () {
      const imgs = Array.from(sandbox.querySelectorAll("img")).filter((img) => {
        const cls = (img.className || "").toString();
        if (cls.includes("ProseMirror-separator")) return false;
        if (img.getAttribute && Number.isFinite(parseFloat(img.getAttribute("data-w")))) return false;
        if (!img.getAttribute("src")) return false;
        return true;
      });
      if (!imgs.length) return;
      const settled = imgs.map((img) => {
        if (img.complete) return Promise.resolve();
        return new Promise((resolve) => {
          const done = () => resolve();
          img.addEventListener("load", done, { once: true });
          img.addEventListener("error", done, { once: true });
          img.addEventListener("DOMNodeRemoved", done, { once: true });
        });
      });
      yield Promise.race([
        Promise.all(settled),
        new Promise((resolve) => setTimeout(resolve, timeoutMs))
      ]);
    });
  }
  function getShellHTML(el) {
    if (!el || typeof el.cloneNode !== "function") return "";
    const clone = el.cloneNode(false);
    clone.removeAttribute("data-blockidx");
    clone.removeAttribute("data-violation-id");
    const tmp = document.createElement("div");
    tmp.appendChild(clone);
    return tmp.innerHTML;
  }
  function getCleanOuterHTML(el) {
    if (!el || typeof el.cloneNode !== "function") return "";
    const clone = el.cloneNode(true);
    clone.removeAttribute("data-blockidx");
    clone.removeAttribute("data-violation-id");
    clone.querySelectorAll("[data-blockidx]").forEach((n) => n.removeAttribute("data-blockidx"));
    clone.querySelectorAll("[data-violation-id]").forEach((n) => n.removeAttribute("data-violation-id"));
    const tmp = document.createElement("div");
    tmp.appendChild(clone);
    return tmp.innerHTML;
  }
  function hasWidthVariance(screenFindings, tolerance = 10, ratioTolerance = 0.2, debug = false) {
    if (!screenFindings.length) return { isValid: true, rules: "" };
    const isOverflowOnly = screenFindings[0].overflowOnly;
    const baseWidth = screenFindings[0].computedWidth;
    const baseRatio = screenFindings[0].widthRatio;
    const baseOverflowing = screenFindings[0].isOverflowing;
    const hasWidthDiff = screenFindings.some((f) => Math.abs(f.computedWidth - baseWidth) > tolerance);
    const isNormalResponsive = hasWidthDiff && screenFindings.every((f) => {
      const sameAsBase = Math.abs(f.computedWidth - baseWidth) <= tolerance;
      const filledScreen = Math.abs(f.widthRatio - 1) < 0.1;
      return sameAsBase || filledScreen;
    });
    const dynamicRatioTolerance = screenFindings.some((f) => f.widthRatio === 1) ? 0 : ratioTolerance;
    const hasRatioDiff = screenFindings.some((f) => Math.abs(f.widthRatio - baseRatio) > dynamicRatioTolerance);
    const hasOverflowDiff = screenFindings.some((f) => f.isOverflowing !== baseOverflowing);
    if (isOverflowOnly) {
      const isActuallyOverflowing = screenFindings.some((f) => f.isOverflowing);
      return { isValid: !isActuallyOverflowing, rules: isActuallyOverflowing ? "\u5B58\u5728\u6EA2\u51FA\u95EE\u9898" : "" };
    }
    const hasCenterInconsistency = screenFindings.some((f) => f.isHorizontallyCentered) && screenFindings.some((f) => !f.isHorizontallyCentered);
    const rulesList = [];
    if (hasWidthDiff && hasRatioDiff && !isNormalResponsive) rulesList.push("\u4E0D\u540C\u5C4F\u5E55\u4E0B\u5BBD\u5EA6\u5DEE\u5F02");
    if (hasCenterInconsistency) rulesList.push("\u5C45\u4E2D\u5E03\u5C40\u4E0D\u4E00\u81F4");
    if (hasOverflowDiff) rulesList.push("\u5B58\u5728\u6EA2\u51FA\u95EE\u9898");
    const isValid = rulesList.length === 0;
    const rules = rulesList.join("\uFF1B");
    if (debug) {
      console.log("[DEBUG hasWidthVariance]", {
        screenCount: screenFindings.length,
        widths: screenFindings.map((f) => `${f.screenWidth}\u2192${f.computedWidth}(ratio=${f.widthRatio.toFixed(3)})`),
        centered: screenFindings.map((f) => `${f.screenWidth}\u2192${f.isHorizontallyCentered}`),
        overflow: screenFindings.map((f) => `${f.screenWidth}\u2192${f.isOverflowing}`),
        hasWidthDiff,
        isNormalResponsive,
        hasRatioDiff,
        hasOverflowDiff,
        hasCenterInconsistency,
        isValid,
        rules: rules || "(\u65E0)"
      });
    }
    return { isValid, rules };
  }
  function hasLineHeightOverlapping(screenFindings) {
    if (!screenFindings.length) return { isValid: true };
    return { isValid: !screenFindings.some((f) => f.isOverlapping) };
  }
  var MAX_DEPTH = 10;
  function findHeightAncestor(chain) {
    for (let i = 0; i < chain.length; i++) {
      const el = chain[i];
      if (!el || typeof el.getAttribute !== "function") continue;
      const styleStr = el.getAttribute("style");
      if (!styleStr) continue;
      const heightMatch = styleStr.match(/(^|;)\s*height\s*:\s*([^;]+)/i);
      if (heightMatch && !/^auto$/i.test(heightMatch[2].trim())) return el;
    }
    return null;
  }
  function checkChildHeightOverflow(parentElement, parentRect, depth = 0, ancestorChain = []) {
    if (!parentElement || !parentRect || depth > MAX_DEPTH) return null;
    const children = Array.from(parentElement.children);
    const currentChain = [...ancestorChain, parentElement];
    for (const child of children) {
      const childHeight = child.offsetHeight;
      const overflowY = window.getComputedStyle(child).overflowY;
      if (overflowY === "auto" || overflowY === "scroll") continue;
      if (parentRect.height > 200 && childHeight > parentRect.height + 20 || parentRect.height <= 200 && childHeight > parentRect.height + 5) {
        return {
          overflowChild: child,
          childHeight,
          parentHeight: parentRect.height,
          suspectAncestor: findHeightAncestor(currentChain)
        };
      }
      const result = checkChildHeightOverflow(child, parentRect, depth + 1, currentChain);
      if (result) return result;
    }
    return null;
  }
  function detectLineHeightOverlap(node) {
    const cs = window.getComputedStyle(node);
    const fontSize = parseFloat(cs.fontSize);
    const lhRaw = cs.lineHeight;
    const lineHeight = lhRaw === "normal" ? fontSize * 1.2 : parseFloat(lhRaw);
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter(
      (r) => r.height > 0 && r.width > 0
    );
    const lines = [];
    for (const r of rects) {
      const top = r.top;
      const bottom = top + r.height;
      const hit = lines.find((l) => {
        const overlap = Math.min(l.bottom, bottom) - Math.max(l.top, top);
        const minH = Math.min(l.bottom - l.top, bottom - top);
        return overlap > minH * 0.5;
      });
      if (hit) {
        hit.top = Math.min(hit.top, top);
        hit.bottom = Math.max(hit.bottom, bottom);
      } else {
        lines.push({ top, bottom });
      }
    }
    const lineCount = lines.length;
    const contentHeight = range.getBoundingClientRect().height;
    let overlapping = false;
    if (Number.isFinite(lineHeight) && lineHeight === 0) {
      overlapping = true;
    } else if (lineCount >= 2) {
      const avgLineHeight = contentHeight / lineCount;
      overlapping = avgLineHeight < fontSize * 0.95;
    }
    return { fontSize, lineHeight, lineCount, contentHeight, overlapping };
  }
  function collectLineHeightFallback(sandbox, debug = false) {
    const blockTags = /* @__PURE__ */ new Set(["p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "a"]);
    const items = [];
    sandbox.querySelectorAll("*").forEach((node) => {
      const tag = node.tagName.toLowerCase();
      if (!blockTags.has(tag)) return;
      const hasDirectText = Array.from(node.childNodes).some(
        (c) => c.nodeType === Node.TEXT_NODE && c.textContent.trim().length > 0
      );
      if (!hasDirectText) return;
      const text = (node.textContent || "").trim().replace(/\s+/g, " ");
      if (!text.length) return;
      const m = detectLineHeightOverlap(node);
      if (debug) {
        console.log("[DEBUG lineHeight]", tag, {
          fontSize: m.fontSize,
          lineHeight: m.lineHeight,
          lineCount: m.lineCount,
          contentHeight: m.contentHeight,
          avgLineHeight: m.lineCount > 0 ? Number((m.contentHeight / m.lineCount).toFixed(2)) : 0,
          overlapThreshold: Number((m.fontSize * 0.95).toFixed(2)),
          textPreview: text.slice(0, 20),
          overlapping: m.overlapping
        });
      }
      if (m.overlapping) {
        items.push({
          node,
          fontSize: m.fontSize,
          lineHeight: m.lineHeight,
          elementHeight: node.getBoundingClientRect().height,
          estLines: m.lineCount,
          text: text.slice(0, 60)
        });
      }
    });
    return items;
  }
  function findParagraphIndexInSandbox(node) {
    let el = node;
    while (el) {
      if (typeof el.getAttribute === "function") {
        const idx = el.getAttribute("data-blockidx");
        if (idx !== null && idx !== void 0 && idx !== "") {
          const parsed = parseInt(idx, 10);
          if (Number.isFinite(parsed)) return parsed;
        }
      }
      el = el.parentNode;
    }
    return -1;
  }
  function detectLayoutIssues() {
    return __async(this, arguments, function* (invalidNodes = [], htmlString = "", opts = {}) {
      const screenConfigs = opts.screenConfigs || DEFAULT_SCREENS;
      const debug = opts.debugSandbox === true;
      const sandbox = createLayoutSandbox(htmlString, { debugSandbox: opts.debugSandbox });
      yield waitForImagesToLoad(sandbox);
      sandbox.querySelectorAll("img").forEach((img) => {
        var _a;
        if ((img.className || "").includes("ProseMirror-separator")) return;
        if (img.complete && img.naturalWidth > 0) return;
        const dataW = parseFloat(img.getAttribute("data-w"));
        const ratio = parseFloat(img.getAttribute("data-ratio"));
        const inlineWidth = img.style.width;
        const htmlWidthAttr = parseFloat(img.getAttribute("width"));
        let width = null;
        if (inlineWidth) width = parseFloat(inlineWidth);
        if ((!width || width <= 0 || Number.isNaN(width)) && Number.isFinite(dataW) && dataW > 0) width = dataW;
        if ((!width || width <= 0 || Number.isNaN(width)) && Number.isFinite(htmlWidthAttr) && htmlWidthAttr > 0) width = htmlWidthAttr;
        if (debug) console.log("[DEBUG img fallback]", { inlineWidth, dataW, ratio, htmlWidthAttr, parsedWidth: width, src: (_a = img.src) == null ? void 0 : _a.substring(0, 80), complete: img.complete, naturalWidth: img.naturalWidth });
        if (width && width > 0 && Number.isFinite(width)) {
          img.style.width = width + "px";
          if (debug) console.log("[DEBUG img fallback] \u2192 \u8BBE\u7F6E width:", width + "px");
          if (ratio && ratio > 0 && Number.isFinite(ratio)) img.style.height = width * ratio + "px";
        } else {
          img.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'%3E%3C/svg%3E";
        }
      });
      try {
        const allScreenFindings = {};
        const caretColorNodes = invalidNodes.filter((n) => n.property === "caret-color");
        const opacityNodes = invalidNodes.filter((n) => n.property === "opacity");
        const textAlignNodes = invalidNodes.filter((n) => n.property === "text-align");
        const animateBeginNodes = invalidNodes.filter((n) => n.property === "animate-begin");
        const preNodes = invalidNodes.filter((n) => n.property === "pre");
        const heightZeroNodes = invalidNodes.filter((n) => n.property === "height");
        Object.assign(sandbox.style, screenConfigs[0].style);
        yield new Promise((r) => setTimeout(r, 100));
        const parentRect = sandbox.getBoundingClientRect();
        const overflowResult = checkChildHeightOverflow(sandbox, parentRect);
        let heightIssues = [];
        if (overflowResult) {
          heightIssues.push({
            violateRules: propertyRules["height-nodisplay"],
            outerHTML: overflowResult.suspectAncestor ? getShellHTML(overflowResult.suspectAncestor) : "",
            childHeight: overflowResult.childHeight,
            parentHeight: overflowResult.parentHeight
          });
        }
        const fallbackItems = collectLineHeightFallback(sandbox, debug);
        for (const config of screenConfigs) {
          Object.assign(sandbox.style, config.style);
          yield new Promise((r) => setTimeout(r, 100));
          const pRect = sandbox.getBoundingClientRect();
          const widthNodes = invalidNodes.filter((n) => n.property === "width");
          const lineHeightNodes = invalidNodes.filter((n) => n.property === "line-height");
          widthNodes.forEach((nodeInfo) => {
            const violationId = nodeInfo.violationId;
            if (!violationId) return;
            const cloned = sandbox.querySelector(`[data-violation-id="${violationId}"]`);
            if (!cloned) return;
            const rect = cloned.getBoundingClientRect();
            const computedWidth = Math.round(parseFloat(rect.width));
            const leftDistance = rect.left - pRect.left;
            const rightDistance = pRect.right - rect.right;
            const horizontalCenterDiff = Math.abs(leftDistance - rightDistance);
            const isHorizontallyCentered = horizontalCenterDiff <= 1;
            const isNotRendered = rect.width === 0 && rect.height === 0;
            const isOverflowing = !isNotRendered && (rect.left < pRect.left - 1 || rect.right > pRect.right + 1) && !isHorizontallyCentered;
            const finding = {
              violationId,
              node: nodeInfo.node,
              property: "width",
              screenWidth: config.width,
              widthRatio: computedWidth / config.width,
              computedWidth: Number.isFinite(computedWidth) ? computedWidth : 0,
              isHeightZero: rect.height < 1,
              isOverflowing,
              isHorizontallyCentered,
              overflowOnly: nodeInfo.overflowOnly || false
            };
            if (!allScreenFindings[violationId]) allScreenFindings[violationId] = { width: [], "line-height": [] };
            allScreenFindings[violationId].width.push(finding);
          });
          lineHeightNodes.forEach((nodeInfo) => {
            const violationId = nodeInfo.violationId;
            if (!violationId) return;
            const cloned = sandbox.querySelector(`[data-violation-id="${violationId}"]`);
            if (!cloned) return;
            const m = detectLineHeightOverlap(cloned);
            const finding = { node: nodeInfo.node, violationId, property: "line-height", isOverlapping: m.overlapping };
            if (!allScreenFindings[violationId]) allScreenFindings[violationId] = { width: [], "line-height": [] };
            allScreenFindings[violationId]["line-height"].push(finding);
          });
          preNodes.forEach((nodeInfo) => {
            const violationId = nodeInfo.violationId;
            if (!violationId) return;
            const cloned = sandbox.querySelector(`[data-violation-id="${violationId}"]`);
            if (!cloned) return;
            const overflowX = getComputedStyle(cloned).overflowX;
            const canScrollX = overflowX === "auto" || overflowX === "scroll";
            const isOverflowing = cloned.scrollWidth > cloned.clientWidth + 1 && !canScrollX;
            if (!allScreenFindings[violationId]) allScreenFindings[violationId] = { width: [], "line-height": [] };
            if (!allScreenFindings[violationId].pre) allScreenFindings[violationId].pre = [];
            const finding = { violationId, isOverflowing, screenWidth: config.width };
            allScreenFindings[violationId].pre.push(finding);
          });
        }
        const optimizedIssues = {};
        Object.entries(allScreenFindings).forEach(([violationId, findings]) => {
          if (findings.width && findings.width.length > 0) {
            if (debug) {
              console.log(`[DEBUG screenFindings] violationId=${violationId}`, findings.width.map((f) => ({
                screenWidth: f.screenWidth,
                computedWidth: f.computedWidth,
                widthRatio: f.widthRatio.toFixed(3),
                isHorizontallyCentered: f.isHorizontallyCentered,
                isOverflowing: f.isOverflowing,
                isHeightZero: f.isHeightZero,
                overflowOnly: f.overflowOnly
              })));
            }
            const { isValid, rules } = hasWidthVariance(findings.width, 10, 0.2, debug);
            if (!isValid) {
              const paragraphIndex = violationId.split("-")[1];
              const itemViolateRulesDesc = WIDTH_DETAIL_RULES[rules] || propertyRules["width"];
              if (!optimizedIssues.width) optimizedIssues.width = { violateRules: propertyRules["width"], items: [] };
              optimizedIssues.width.items.push({
                violationId,
                screenFindings: findings.width,
                rules,
                paragraphIndex,
                outerHTML: getCleanOuterHTML(findings.width[0].node),
                violateRules: itemViolateRulesDesc
              });
            }
          }
          if (findings["line-height"].length > 0) {
            const { isValid } = hasLineHeightOverlapping(findings["line-height"]);
            if (!isValid) {
              const paragraphIndex = violationId.split("-")[1];
              if (!optimizedIssues["line-height"]) optimizedIssues["line-height"] = { violateRules: propertyRules["line-height-overlapping"], items: [] };
              optimizedIssues["line-height"].items.push({
                violationId,
                screenFindings: findings["line-height"],
                paragraphIndex,
                outerHTML: getCleanOuterHTML(findings["line-height"][0].node)
              });
            }
          }
        });
        if (heightIssues.length > 0) {
          optimizedIssues["height-nodisplay"] = { violateRules: propertyRules["height-nodisplay"], items: heightIssues };
        }
        if (heightZeroNodes.length > 0) optimizedIssues.height = { violateRules: propertyRules["height"], items: heightZeroNodes };
        if (caretColorNodes.length > 0) optimizedIssues["caret-color"] = { violateRules: propertyRules["caret-color"], items: caretColorNodes };
        if (opacityNodes.length > 0) optimizedIssues.opacity = { violateRules: propertyRules["opacity"], items: opacityNodes };
        if (animateBeginNodes.length > 0) optimizedIssues["animate-begin"] = { violateRules: propertyRules["animate-begin"], items: animateBeginNodes };
        if (textAlignNodes.length > 0) optimizedIssues["text-align"] = { violateRules: propertyRules["text-align"], items: textAlignNodes };
        if (preNodes.length > 0) {
          const preOverflowItems = [];
          preNodes.forEach((preNode) => {
            const violationId = preNode.violationId;
            if (!violationId) return;
            const findings = allScreenFindings[violationId];
            if (!findings || !findings.pre || !findings.pre.length) return;
            if (findings.pre.some((f) => f.isOverflowing)) {
              preOverflowItems.push({ violationId, paragraphIndex: preNode.paragraphIndex, outerHTML: getCleanOuterHTML(preNode.node) });
            }
          });
          if (preOverflowItems.length > 0) optimizedIssues["pre"] = { violateRules: propertyRules["pre"], items: preOverflowItems };
        }
        if (fallbackItems.length > 0) {
          let localCounter = 0;
          if (!optimizedIssues["line-height"]) optimizedIssues["line-height"] = { violateRules: propertyRules["line-height-overlapping"], items: [] };
          fallbackItems.forEach((it) => {
            const paragraphIndex = findParagraphIndexInSandbox(it.node);
            const safePIdx = paragraphIndex >= 0 ? paragraphIndex : -1;
            let violationId = null;
            const node = it.node;
            if (node && typeof node.getAttribute === "function" && typeof node.setAttribute === "function") {
              const existing = node.getAttribute("data-violation-id");
              if (existing) {
                violationId = existing;
              } else {
                violationId = `violation-${safePIdx}-${localCounter++}-${Date.now()}`;
                node.setAttribute("data-violation-id", violationId);
              }
            }
            optimizedIssues["line-height"].items.push({
              violationId,
              paragraphIndex: safePIdx,
              outerHTML: getCleanOuterHTML(it.node),
              rules: it.lineHeight === 0 ? "\u7EE7\u627F\u7684 line-height: 0 \u5BFC\u81F4\u6587\u5B57\u53E0\u5B57\uFF08\u515C\u5E95\u68C0\u6D4B\uFF09" : "\u884C\u9AD8\u5C0F\u4E8E\u5B57\u4F53\u5927\u5C0F\uFF0C\u4E14\u5B58\u5728\u591A\u884C\u6587\u672C\uFF0C\u53EF\u80FD\u5BFC\u81F4\u6587\u5B57\u91CD\u53E0\uFF08\u5B9E\u6D4B\uFF09"
            });
          });
        }
        if (debug) {
          const summary = {};
          Object.entries(optimizedIssues).forEach(([key, entry]) => {
            var _a;
            summary[key] = {
              violateRules: entry.violateRules,
              count: ((_a = entry.items) == null ? void 0 : _a.length) || 0,
              items: (entry.items || []).map((it) => {
                var _a2;
                return {
                  violationId: it.violationId,
                  rules: it.rules,
                  paragraphIndex: it.paragraphIndex,
                  outerHTML: (_a2 = it.outerHTML) == null ? void 0 : _a2.substring(0, 120)
                };
              })
            };
          });
          console.log("[DEBUG detectLayoutIssues] \u6700\u7EC8\u7ED3\u679C:", JSON.stringify(summary, null, 2));
        }
        return optimizedIssues;
      } finally {
        removeLayoutSandbox(sandbox);
      }
    });
  }

  // engine/rules/helpers.ts
  function getInlineStyleValue(node, propName) {
    if (!node) return null;
    const styleStr = node.getAttribute("style");
    if (!styleStr) return null;
    const regex = new RegExp("(^|;)\\s*" + propName + "\\s*:\\s*([^;]+)", "i");
    const match = styleStr.match(regex);
    return match ? match[2].trim() : null;
  }
  function isTransparentRgba(value) {
    if (!value) return false;
    return /rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)/i.test(value.replace(/\s+/g, ""));
  }

  // engine/rules/font-family.ts
  var normalizeFontFamily = (fontStr) => fontStr.replace(/["']/g, "").replace(/\s+/g, " ").trim();
  var allowedFontFamily = normalizeFontFamily('"mp-quote", PingFang SC, system-ui, -apple-system');

  // engine/rules/opacity.ts
  function checkOpacityViolation(n, paragraphIndex, propertyMaps, tag, ctx) {
    if (tag !== "img") return null;
    const op = ctx.getInlineStyleValue(n, "opacity");
    const s = n.getAttribute("style") || "";
    if (op !== null && (/^0(?:\.0+)?$/.test(op) || parseFloat(op) === 0) || /opacity\s*:\s*0\b/i.test(s)) {
      const item = {
        paragraphIndex,
        node: n,
        property: "opacity",
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n),
        value: op !== null ? op : "0 (from style attribute)"
      };
      propertyMaps["opacity"].set(paragraphIndex, item);
      return item;
    }
    return null;
  }

  // engine/rules/caret-color.ts
  function checkCaretColorViolation(n, paragraphIndex, propertyMaps, ctx) {
    const caret = ctx.getInlineStyleValue(n, "caret-color");
    if (caret && ctx.isTransparentRgba(caret)) {
      const item = {
        paragraphIndex,
        node: n,
        property: "caret-color",
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n)
      };
      if (!ctx.isEmptyParagraph(n)) propertyMaps["caret-color"].set(paragraphIndex, item);
      return item;
    }
    return null;
  }

  // engine/rules/line-height.ts
  function checkLineHeightViolation(n, paragraphIndex, propertyMaps, tag, ctx) {
    if (tag === "svg") return null;
    const textContent = n.textContent ? n.textContent.replace(/​/g, "").replace(/ /g, "").replace(/\s+/g, "") : null;
    const lh = ctx.getInlineStyleValue(n, "line-height");
    if (lh !== null && /^0(px)?$/i.test(lh.trim())) {
      if (!textContent) return null;
    }
    if (textContent) {
      const item = {
        paragraphIndex,
        node: n,
        property: "line-height",
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n)
      };
      propertyMaps["line-height"].set(paragraphIndex, item);
      return item;
    }
    return null;
  }

  // engine/rules/width.ts
  function checkWidthViolation(n, paragraphIndex, propertyMaps, tag, ctx) {
    if (n.closest && n.closest("[data-ignore-width]")) return null;
    if (!n.closest && n.hasAttribute && n.hasAttribute("data-ignore-width")) return null;
    if (tag === "img" && !n.classList.contains("ProseMirror-separator")) {
      const item = {
        paragraphIndex,
        node: n,
        property: "width",
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n)
      };
      propertyMaps["width"].set(paragraphIndex, item);
      return item;
    }
    const w = ctx.getInlineStyleValue(n, "width");
    if (tag === "table") {
      const thead = n.querySelector("thead");
      if (thead) {
        thead.querySelectorAll("th").forEach((th, thIndex) => {
          const item = {
            paragraphIndex,
            node: th,
            property: "width",
            rule: ctx.propertyRules["width"],
            violationId: ctx.ensureViolationId(th, paragraphIndex),
            thIndex
          };
          propertyMaps["width"].set(`${paragraphIndex}_th${thIndex}`, item);
        });
      }
      return null;
    }
    if (tag !== "img" && tag !== "svg" && w !== null && w !== "" && !/auto|100%/i.test(w)) {
      const item = {
        paragraphIndex,
        node: n,
        property: "width",
        value: w,
        rule: ctx.propertyRules["width"],
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n)
      };
      propertyMaps["width"].set(paragraphIndex, item);
      return item;
    }
    return null;
  }

  // engine/rules/text-align.ts
  var LOGICAL_ALIGN = /^(start|end)$/i;
  function resolveSide(value, rtl) {
    const v = value.trim().toLowerCase();
    if (v === "start") return rtl ? "right" : "left";
    if (v === "end") return rtl ? "left" : "right";
    return v;
  }
  function isRtlDirection(value) {
    return !!value && /^rtl$/i.test(value.trim());
  }
  function checkTextAlignViolation(n, paragraphIndex, propertyMaps, ctx) {
    const ta = ctx.getInlineStyleValue(n, "text-align");
    if (!ta || !LOGICAL_ALIGN.test(ta)) return null;
    const nodeRtl = isRtlDirection(ctx.getInlineStyleValue(n, "direction"));
    let rtl = nodeRtl;
    let ancestor = n.parentNode;
    let ancestorTa = null;
    while (ancestor) {
      if (isRtlDirection(ctx.getInlineStyleValue(ancestor, "direction"))) rtl = true;
      const v = ctx.getInlineStyleValue(ancestor, "text-align");
      if (v) {
        ancestorTa = v;
        break;
      }
      ancestor = ancestor.parentNode;
    }
    const nodeSide = resolveSide(ta, nodeRtl);
    const ancestorSide = ancestorTa ? resolveSide(ancestorTa, rtl) : "left";
    const conflict = nodeSide !== ancestorSide && !(nodeSide === "left" && ancestorSide === "justify");
    if (!conflict) return null;
    const item = {
      paragraphIndex,
      node: n,
      property: "text-align",
      value: ta,
      violationId: ctx.ensureViolationId(n, paragraphIndex),
      outerHTML: ctx.getCleanOuterHTML(n)
    };
    propertyMaps["text-align"].set(paragraphIndex, item);
    return item;
  }

  // engine/rules/animate-begin.ts
  function checkAnimateBeginViolation(n, paragraphIndex, propertyMaps, tag, ctx) {
    if (tag !== "animate" && tag !== "animatetransform" && tag !== "animatemotion") return null;
    const beginAttr = n.getAttribute && n.getAttribute("begin");
    if (beginAttr && /\btouchstart\b/i.test(beginAttr) && !/\bclick\b/i.test(beginAttr)) {
      const item = {
        paragraphIndex,
        node: n,
        property: "animate-begin",
        value: beginAttr,
        violationId: ctx.ensureViolationId(n, paragraphIndex),
        outerHTML: ctx.getCleanOuterHTML(n)
      };
      propertyMaps["animate-begin"].set(paragraphIndex, item);
      return item;
    }
    return null;
  }

  // engine/rules/height-zero.ts
  function checkHeightZeroViolation(n, paragraphIndex, propertyMaps, tag, isInsideSvg, isInsideSvgMode, ctx) {
    if (isInsideSvg || isInsideSvgMode) return null;
    const h = ctx.getInlineStyleValue(n, "height");
    if (h !== null && /^0(px)?$/i.test(h.trim())) {
      const textContent = n.textContent ? n.textContent.replace(/​/g, "").replace(/ /g, "").replace(/\s+/g, "") : "";
      if (textContent.length > 0) {
        const violationId = ctx.ensureViolationId(n, paragraphIndex);
        const item = {
          paragraphIndex,
          node: n,
          property: "height",
          value: h,
          violationId,
          outerHTML: ctx.getCleanOuterHTML(n)
        };
        propertyMaps["height"].set(violationId, item);
        return item;
      }
    }
    return null;
  }

  // engine/rules/pre.ts
  function checkPreViolation(n, paragraphIndex, propertyMaps, ctx) {
    const textContent = n.textContent ? n.textContent.replace(/​|\s/g, "") : "";
    if (textContent.length === 0) return null;
    const violationId = ctx.ensureViolationId(n, paragraphIndex);
    const item = {
      paragraphIndex,
      node: n,
      property: "pre",
      violationId,
      outerHTML: ctx.getCleanOuterHTML(n)
    };
    propertyMaps["pre"].set(paragraphIndex, item);
    return item;
  }

  // engine/collect.ts
  var commentRegex = /<!--[\s\S]*?-->/g;
  var quickRegex = /\b(?:font-family|caret-color|opacity|line-height|text-align|width|height|animate(?:Transform|Motion)?)\b|<pre[\s>]/i;
  function toArray(maybeList) {
    if (!maybeList) return [];
    if (Array.isArray(maybeList)) return maybeList;
    try {
      return Array.prototype.slice.call(maybeList);
    } catch (e) {
      return [];
    }
  }
  function makeContext() {
    let counter = 0;
    const ensureViolationId = (node, paragraphIndex) => {
      if (!node || typeof node.getAttribute !== "function" || typeof node.setAttribute !== "function") return null;
      const existing = node.getAttribute("data-violation-id");
      if (existing) return existing;
      const id = `violation-${paragraphIndex}-${counter++}-${Date.now()}`;
      node.setAttribute("data-violation-id", id);
      return id;
    };
    return { getInlineStyleValue, isTransparentRgba, isEmptyParagraph, getCleanOuterHTML, propertyRules, ensureViolationId };
  }
  function collectViolationsInParagraph(paragraphNode, paragraphIndex) {
    const found = [];
    if (!paragraphNode) return found;
    if (isEmptyParagraph(paragraphNode)) return found;
    const ctx = makeContext();
    const propertyMaps = {
      "line-height": /* @__PURE__ */ new Map(),
      "width": /* @__PURE__ */ new Map(),
      "height": /* @__PURE__ */ new Map(),
      "caret-color": /* @__PURE__ */ new Map(),
      "opacity": /* @__PURE__ */ new Map(),
      "text-align": /* @__PURE__ */ new Map(),
      "animate-begin": /* @__PURE__ */ new Map(),
      "pre": /* @__PURE__ */ new Map()
    };
    if (!(paragraphNode.hasAttribute && paragraphNode.hasAttribute("data-ignore-width"))) {
      const paraViolationId = ctx.ensureViolationId(paragraphNode, paragraphIndex);
      propertyMaps["width"].set(`${paragraphIndex}_para`, {
        paragraphIndex,
        node: paragraphNode,
        property: "width",
        violationId: paraViolationId,
        outerHTML: paragraphNode.outerHTML,
        overflowOnly: true
      });
    }
    const q = [{ node: paragraphNode, isInsideSvg: false, isInsideSvgMode: false }];
    while (q.length) {
      const { node: n, isInsideSvg, isInsideSvgMode } = q.shift();
      const tag = n.tagName && typeof n.tagName === "string" ? n.tagName.toLowerCase() : "";
      n.setAttribute("data-blockidx", String(paragraphIndex));
      const currentInsideSvg = isInsideSvg || tag === "svg";
      const currentInsideSvgMode = isInsideSvgMode || n.getAttribute && n.getAttribute("data-mode") === "svg";
      const opacity = checkOpacityViolation(n, paragraphIndex, propertyMaps, tag, ctx);
      if (opacity) found.push(opacity);
      const caretColor = checkCaretColorViolation(n, paragraphIndex, propertyMaps, ctx);
      if (caretColor) found.push(caretColor);
      const lineHeight = checkLineHeightViolation(n, paragraphIndex, propertyMaps, tag, ctx);
      if (lineHeight) found.push(lineHeight);
      const width = checkWidthViolation(n, paragraphIndex, propertyMaps, tag, ctx);
      if (width) found.push(width);
      const textAlign = checkTextAlignViolation(n, paragraphIndex, propertyMaps, ctx);
      if (textAlign) found.push(textAlign);
      const animateBegin = checkAnimateBeginViolation(n, paragraphIndex, propertyMaps, tag, ctx);
      if (animateBegin) found.push(animateBegin);
      const heightZero = checkHeightZeroViolation(n, paragraphIndex, propertyMaps, tag, currentInsideSvg, currentInsideSvgMode, ctx);
      if (heightZero) found.push(heightZero);
      if (tag === "pre") {
        const pre = checkPreViolation(n, paragraphIndex, propertyMaps, ctx);
        if (pre) found.push(pre);
      }
      const children = toArray(n.children || n.childNodes);
      for (let i = 0; i < children.length; i++) {
        q.push({ node: children[i], isInsideSvg: currentInsideSvg, isInsideSvgMode: currentInsideSvgMode });
      }
    }
    const allResults = [];
    for (const map of Object.values(propertyMaps)) allResults.push(...Array.from(map.values()));
    return allResults;
  }
  function stampParagraphSubtree(paragraphNode, paragraphIndex) {
    if (!paragraphNode || typeof paragraphNode.setAttribute !== "function") return;
    const q = [paragraphNode];
    while (q.length) {
      const n = q.shift();
      if (n && typeof n.setAttribute === "function") {
        n.setAttribute("data-blockidx", String(paragraphIndex));
      }
      const children = toArray(n.children || n.childNodes);
      for (let i = 0; i < children.length; i++) q.push(children[i]);
    }
  }
  function getInvalidNodes(paragraphList) {
    const invalid = [];
    for (let i = 0; i < paragraphList.length; i++) {
      const pNode = paragraphList[i];
      if (!pNode || typeof pNode.parentNode === "undefined") continue;
      let anc = pNode.parentNode;
      while (anc && typeof anc.getAttribute === "function" && typeof anc.setAttribute === "function") {
        if (anc.getAttribute("data-blockidx") !== null) break;
        anc.setAttribute("data-blockidx", String(i));
        anc = anc.parentNode;
      }
    }
    paragraphList.forEach((pNode, idx) => {
      if (!pNode) return;
      stampParagraphSubtree(pNode, idx);
      let htmlStr = "";
      if (typeof pNode.outerHTML === "string") {
        htmlStr = pNode.outerHTML.replace(commentRegex, "");
      } else if (typeof pNode.innerHTML === "string") {
        htmlStr = `<root>${pNode.innerHTML}</root>`.replace(commentRegex, "");
      } else if (pNode.html) {
        htmlStr = String(pNode.html).replace(commentRegex, "");
      }
      if (htmlStr && !quickRegex.test(htmlStr)) return;
      const founds = collectViolationsInParagraph(pNode, idx);
      for (let j = 0; j < founds.length; j++) invalid.push(founds[j]);
    });
    return { isValid: invalid.length === 0, invalidNodes: invalid };
  }

  // engine/index.ts
  function resolveParagraphIndex(node, paragraphList) {
    let el = node;
    while (el) {
      if (typeof el.getAttribute === "function") {
        const editorIdx = el.getAttribute("data-para-index");
        if (editorIdx !== null && editorIdx !== "") {
          const n = parseInt(editorIdx, 10);
          if (Number.isFinite(n)) return n;
        }
      }
      el = el.parentNode;
    }
    el = node;
    while (el) {
      if (typeof el.getAttribute === "function") {
        const idx = el.getAttribute("data-blockidx");
        if (idx !== null && idx !== void 0 && idx !== "") {
          const i = parseInt(idx, 10);
          const p = paragraphList[i];
          if (p && typeof p.contains === "function" && p.contains(node)) return i;
        }
      }
      el = el.parentNode;
    }
    return paragraphList.findIndex((p) => p && p.contains && p.contains(node));
  }
  function verifyArticleStructure(_0) {
    return __async(this, arguments, function* (articleBody, opts = {}) {
      const nodes = articleBody.querySelectorAll("*");
      const doc = typeof document !== "undefined" ? document : null;
      const detached = doc && doc.body && !articleBody.parentNode;
      if (detached) doc.body.appendChild(articleBody);
      import_mp_darkmode.default.reset(nodes);
      import_mp_darkmode.default.run(nodes, {
        mode: "dark",
        defaultDarkTextColor: "#989898",
        whitelist: { attribute: ["data-no-dark"] },
        needJudgeFirstPage: false,
        noEmit: true
      });
      const darkmodeResult = import_mp_darkmode.default.validate(articleBody, { minContrast: 1.5 });
      if (detached) doc.body.removeChild(articleBody);
      const paragraphList = paragraph_default(articleBody, {
        isMarkNode(node) {
          return domUtils.isMarkNode(node);
        },
        getNestedStructure: opts.getNestedStructure,
        ignoreFlexChildren: opts.ignoreFlexChildren,
        ignoreNotWriteableChildren: opts.ignoreNotWriteableChildren,
        getSpan: opts.getSpan
      });
      const nestedNodes = deleteNestNode({ root: articleBody, isTest: true }) || [];
      const invalidNodesResult = getInvalidNodes(paragraphList);
      const fullHtmlString = articleBody && articleBody.outerHTML ? articleBody.outerHTML : articleBody && articleBody.innerHTML ? `<section>${articleBody.innerHTML}</section>` : "";
      const layoutIssues = yield detectLayoutIssues(
        invalidNodesResult.invalidNodes,
        fullHtmlString,
        opts.layoutDetectOptions
      );
      if (nestedNodes.length > 0) {
        const byPara = /* @__PURE__ */ new Map();
        nestedNodes.forEach((item) => {
          const paragraphIndex = resolveParagraphIndex(item, paragraphList);
          const outerHTML = item.outerHTML || "";
          const key = paragraphIndex !== void 0 && paragraphIndex !== -1 ? `p_${paragraphIndex}` : item;
          const exist = byPara.get(key);
          if (!exist || (exist.outerHTML || "").length < outerHTML.length) {
            byPara.set(key, { paragraphIndex, outerHTML });
          }
        });
        layoutIssues.nestNodes = { violateRules: propertyRules["nest-level"], items: Array.from(byPara.values()) };
      }
      if (darkmodeResult.length > 0) {
        const byKey = {};
        darkmodeResult.forEach((item) => {
          if (!item || !item.key) return;
          if (!byKey[item.key]) byKey[item.key] = { violateRules: item.violateRules || "", items: [] };
          byKey[item.key].items.push({
            outerHTML: item.outerHTML || (item.dom ? item.dom.outerHTML : ""),
            // 用违规 dom 节点反查真实段号（mp-darkmode 不返回段落信息，旧逻辑
            // `|| 0` 把所有 item 兜底成第 1 段，编辑器「定位」按钮全部跳错）。
            // dom 已在原始容器上，data-blockidx 由 getInvalidNodes 盖章，可反查。
            // 找不到时返回 -1（诚实未知），不要假装成第 1 段。
            paragraphIndex: resolveParagraphIndex(item.dom, paragraphList)
          });
        });
        Object.assign(layoutIssues, byKey);
      }
      const filteredInfo = {};
      for (const [property, issueGroup] of Object.entries(layoutIssues)) {
        filteredInfo[property] = {
          violateRules: issueGroup.violateRules,
          items: issueGroup.items.map((item) => {
            const filtered = { paragraphIndex: item.paragraphIndex, outerHTML: item.outerHTML };
            if (item.rules) filtered.rules = item.rules;
            if (item.thIndex !== void 0) filtered.thIndex = item.thIndex;
            return filtered;
          })
        };
      }
      const hasInValidData = Object.values(filteredInfo).some((g) => g.items && g.items.length > 0);
      return hasInValidData ? { isValid: false, inValidInfo: filteredInfo } : { isValid: true, inValidInfo: {} };
    });
  }
  return __toCommonJS(engine_exports);
})();
