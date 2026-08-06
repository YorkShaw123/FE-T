#!/usr/bin/env python3
"""
代码审查工具
支持多种编程语言的静态代码分析
基于华为Java编程规范进行代码质量评分
"""

import os
import re
import json
import ast
import argparse
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime


class HuaweiJavaReviewer:
    """基于华为Java编程规范的代码审查器"""

    def __init__(self):
        self.score = {
            'layout': {'score': 20, 'deductions': [], 'suggestions': []},
            'comment': {'score': 25, 'deductions': [], 'suggestions': []},
            'naming': {'score': 20, 'deductions': [], 'suggestions': []},
            'coding': {'score': 20, 'deductions': [], 'suggestions': []},
            'performance': {'score': 15, 'deductions': [], 'suggestions': []}
        }

    def review(self, content: str, filepath: Path) -> Dict[str, Any]:
        """审查Java代码并计算评分"""
        lines = content.split('\n')

        # 1. 排版规范检查（20分）
        self._check_layout(lines)

        # 2. 注释规范检查（25分）
        self._check_comment(content, lines)

        # 3. 命名规范检查（20分）
        self._check_naming(content, lines)

        # 4. 代码编写规范检查（20分）
        self._check_coding(content, lines)

        # 5. 性能与可靠性检查（15分）
        self._check_performance(content, lines)

        # 计算总分
        total_score = sum(cat['score'] for cat in self.score.values())

        return {
            'total_score': total_score,
            'categories': self.score,
            'grade': self._get_grade(total_score)
        }

    def _check_layout(self, lines: List[str]):
        """检查排版规范"""
        tab_count = 0
        long_lines = 0
        multi_statement_lines = 0
        brace_not_alone = 0

        for i, line in enumerate(lines):
            # 规则1：检查是否使用TAB缩进
            if '\t' in line and line.startswith('\t'):
                tab_count += 1

            # 规则3：检查行长度（>80字符）
            if len(line) > 80:
                long_lines += 1

            # 规则4：检查一行是否有多条语句
            if ';' in line and line.count(';') > 1 and not line.strip().startswith('//'):
                multi_statement_lines += 1

            # 规则2：检查分界符是否独占一行
            stripped = line.strip()
            if stripped == '{' or stripped == '}':
                continue
            if '{' in stripped or '}' in stripped:
                if not stripped.startswith('//') and not stripped.startswith('/*'):
                    brace_not_alone += 1

        # 扣分计算
        if tab_count > 0:
            deduction = min(5, tab_count)
            self.score['layout']['score'] -= deduction
            self.score['layout']['deductions'].append({
                'rule': '规则1',
                'desc': f'发现{tab_count}处使用TAB缩进',
                'deduction': deduction
            })
            self.score['layout']['suggestions'].append('使用4个空格进行缩进，不使用TAB')

        if long_lines > 3:
            deduction = min(5, long_lines // 2)
            self.score['layout']['score'] -= deduction
            self.score['layout']['deductions'].append({
                'rule': '规则3',
                'desc': f'发现{long_lines}行超过80字符',
                'deduction': deduction
            })
            self.score['layout']['suggestions'].append('长语句应在低优先级操作符处换行')

        if multi_statement_lines > 0:
            deduction = min(3, multi_statement_lines)
            self.score['layout']['score'] -= deduction
            self.score['layout']['deductions'].append({
                'rule': '规则4',
                'desc': f'发现{multi_statement_lines}行包含多条语句',
                'deduction': deduction
            })
            self.score['layout']['suggestions'].append('一行只写一条语句')

        if brace_not_alone > 2:
            deduction = min(4, brace_not_alone // 2)
            self.score['layout']['score'] -= deduction
            self.score['layout']['deductions'].append({
                'rule': '规则2',
                'desc': f'发现{brace_not_alone}处分界符未独占一行',
                'deduction': deduction
            })
            self.score['layout']['suggestions'].append('分界符应独占一行，与引用它们的语句左对齐')

    def _check_comment(self, content: str, lines: List[str]):
        """检查注释规范"""
        # 规则1：注释量检查（30%以上）
        comment_lines = 0
        code_lines = 0
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('//') and not stripped.startswith('/*') and not stripped.startswith('*'):
                code_lines += 1
            if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
                comment_lines += 1

        comment_ratio = comment_lines / max(code_lines + comment_lines, 1) * 100

        if comment_ratio < 30:
            deduction = min(10, int((30 - comment_ratio) / 3))
            self.score['comment']['score'] -= deduction
            self.score['comment']['deductions'].append({
                'rule': '规则1',
                'desc': f'注释覆盖率仅{comment_ratio:.1f}%，低于30%要求',
                'deduction': deduction
            })
            self.score['comment']['suggestions'].append('增加代码注释，确保注释量达到30%以上')

        # 规则3：类是否有JavaDoc注释
        class_pattern = r'(public|protected|private)?\s*class\s+\w+'
        if re.search(class_pattern, content):
            if '/**' not in content:
                self.score['comment']['score'] -= 5
                self.score['comment']['deductions'].append({
                    'rule': '规则3',
                    'desc': '类缺少JavaDoc注释',
                    'deduction': 5
                })
                self.score['comment']['suggestions'].append('为类添加JavaDoc注释，包含功能描述、@author、@since等信息')

        # 规则5：方法是否有完整的JavaDoc注释
        method_pattern = r'(public|protected)\s+\w+\s+\w+\s*\('
        methods = re.findall(method_pattern, content)
        javadoc_count = content.count('@param')
        if len(methods) > 0 and javadoc_count < len(methods):
            deduction = min(5, len(methods) - javadoc_count)
            self.score['comment']['score'] -= deduction
            self.score['comment']['deductions'].append({
                'rule': '规则5',
                'desc': f'公有/保护方法缺少完整的JavaDoc注释（@param、@return等）',
                'deduction': deduction
            })
            self.score['comment']['suggestions'].append('为公有和保护方法添加完整的JavaDoc注释')

    def _check_naming(self, content: str, lines: List[str]):
        """检查命名规范"""
        # 类名检查：PascalCase
        class_pattern = r'class\s+([a-z][a-zA-Z0-9]*)'
        bad_classes = re.findall(class_pattern, content)
        if bad_classes:
            self.score['naming']['score'] -= 3
            self.score['naming']['deductions'].append({
                'rule': '规则1',
                'desc': f'类名不符合PascalCase规范：{", ".join(bad_classes[:3])}',
                'deduction': 3
            })
            self.score['naming']['suggestions'].append('类名使用PascalCase，首字母大写')

        # 方法名检查：camelCase
        method_pattern = r'(public|private|protected)\s+\w+\s+([A-Z][a-zA-Z0-9]*)\s*\('
        bad_methods = re.findall(method_pattern, content)
        if bad_methods:
            deduction = min(5, len(bad_methods))
            self.score['naming']['score'] -= deduction
            self.score['naming']['deductions'].append({
                'rule': '规则2',
                'desc': f'方法名不符合camelCase规范：{", ".join([m[1] for m in bad_methods[:3]])}',
                'deduction': deduction
            })
            self.score['naming']['suggestions'].append('方法名使用camelCase，首字母小写')

        # 常量名检查：UPPER_SNAKE_CASE
        const_pattern = r'(public|private|protected)?\s*(static\s+)?(final\s+)?\w+\s+([a-z][a-zA-Z0-9_]*)\s*='
        bad_consts = re.findall(const_pattern, content)
        if bad_consts:
            deduction = min(3, len(bad_consts))
            self.score['naming']['score'] -= deduction
            self.score['naming']['deductions'].append({
                'rule': '规则4',
                'desc': '常量名不符合UPPER_SNAKE_CASE规范',
                'deduction': deduction
            })
            self.score['naming']['suggestions'].append('常量名使用UPPER_SNAKE_CASE，全大写下划线分隔')

        # 变量名检查：camelCase
        var_pattern = r'(int|String|boolean|double|float|long)\s+([A-Z][a-zA-Z0-9]*)\s*[=;]'
        bad_vars = re.findall(var_pattern, content)
        if bad_vars:
            deduction = min(3, len(bad_vars))
            self.score['naming']['score'] -= deduction
            self.score['naming']['deductions'].append({
                'rule': '规则3',
                'desc': f'变量名不符合camelCase规范：{", ".join([v[1] for v in bad_vars[:3]])}',
                'deduction': deduction
            })
            self.score['naming']['suggestions'].append('变量名使用camelCase，首字母小写')

    def _check_coding(self, content: str, lines: List[str]):
        """检查代码编写规范"""
        # 规则9：检查是否使用System.out
        if 'System.out.print' in content or 'System.err.print' in content:
            self.score['coding']['score'] -= 5
            self.score['coding']['deductions'].append({
                'rule': '规则9',
                'desc': '使用System.out/System.err进行控制台打印',
                'deduction': 5
            })
            self.score['coding']['suggestions'].append('使用日志工具类（如Logger）代替System.out打印')

        # 规则7：检查魔法数字
        magic_pattern = r'(?<!["\'\w])(\d{2,})(?!["\'\w])'
        magic_numbers = re.findall(magic_pattern, content)
        # 排除常见的数字（0, 1, 2, -1等）
        magic_numbers = [n for n in magic_numbers if n not in ['0', '1', '2', '-1']]
        if len(magic_numbers) > 5:
            deduction = min(5, len(magic_numbers) // 2)
            self.score['coding']['score'] -= deduction
            self.score['coding']['deductions'].append({
                'rule': '规则7',
                'desc': f'发现{len(magic_numbers)}个魔法数字',
                'deduction': deduction
            })
            self.score['coding']['suggestions'].append('使用有意义的常量代替魔法数字')

        # 规则11：检查集合是否指定泛型类型
        collection_pattern = r'(List|Map|Set|ArrayList|HashMap|HashSet)\s*<\s*>'
        if re.search(collection_pattern, content):
            self.score['coding']['score'] -= 3
            self.score['coding']['deductions'].append({
                'rule': '规则11',
                'desc': '集合未指定泛型类型',
                'deduction': 3
            })
            self.score['coding']['suggestions'].append('为集合指定泛型类型，如List<String>')

        # 规则14：检查 == true 的使用
        if re.search(r'==\s*true', content):
            self.score['coding']['score'] -= 2
            self.score['coding']['deductions'].append({
                'rule': '规则14',
                'desc': '使用 "== true" 进行布尔判断',
                'deduction': 2
            })
            self.score['coding']['suggestions'].append('直接使用布尔变量进行判断，如 if (flag)')

    def _check_performance(self, content: str, lines: List[str]):
        """检查性能与可靠性"""
        # 规则1：日志输出前是否判断级别
        if 'logger.debug' in content or 'logger.info' in content:
            if 'isDebugEnabled' not in content and 'isInfoEnabled' not in content:
                self.score['performance']['score'] -= 3
                self.score['performance']['deductions'].append({
                    'rule': '规则1',
                    'desc': '日志输出前未判断调试级别',
                    'deduction': 3
                })
                self.score['performance']['suggestions'].append('日志输出前先判断级别，如 if (logger.isDebugEnabled())')

        # 规则4：字符串拼接是否使用StringBuilder/StringBuffer
        string_concat_pattern = r'String\s+\w+\s*=.*\+.*;'
        string_concats = re.findall(string_concat_pattern, content)
        if len(string_concats) > 3:
            deduction = min(5, len(string_concats) // 2)
            self.score['performance']['score'] -= deduction
            self.score['performance']['deductions'].append({
                'rule': '规则4',
                'desc': f'发现{len(string_concats)}处字符串拼接，建议使用StringBuilder',
                'deduction': deduction
            })
            self.score['performance']['suggestions'].append('大量字符串拼接使用StringBuilder或StringBuffer')

        # 规则5：logger是否声明为static
        logger_pattern = r'(private|protected|public)\s+(?!static)\s*\w*Logger\s+\w+'
        if re.search(logger_pattern, content):
            self.score['performance']['score'] -= 2
            self.score['performance']['deductions'].append({
                'rule': '规则5',
                'desc': 'Logger对象未声明为static',
                'deduction': 2
            })
            self.score['performance']['suggestions'].append('Logger对象应声明为static final')

    def _get_grade(self, score: int) -> str:
        """根据分数返回评级"""
        if score >= 90:
            return '优秀'
        elif score >= 80:
            return '良好'
        elif score >= 70:
            return '合格'
        elif score >= 60:
            return '需改进'
        else:
            return '不合格'


class CodeReviewer:
    """代码审查器"""

    # 支持的文件扩展名及其对应的语言
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
    }

    # 问题严重性级别
    SEVERITY_CRITICAL = '严重'
    SEVERITY_NORMAL = '一般'
    SEVERITY_OPTIMIZE = '优化'

    def __init__(self, input_dir: str, file_ext: str = None):
        self.input_dir = Path(input_dir)
        self.file_ext = file_ext
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'input_dir': str(self.input_dir),
            'total_files': 0,
            'files_analyzed': 0,
            'issues': {
                'critical': [],
                'normal': [],
                'optimize': []
            },
            'file_details': {},
            'statistics': {
                'total_lines': 0,
                'comment_lines': 0,
                'comment_coverage': 0.0
            },
            'huawei_score': None  # 华为规范评分
        }

    def detect_language(self, filepath: Path) -> str:
        """根据文件扩展名检测编程语言"""
        suffix = filepath.suffix.lower()
        return self.LANGUAGE_MAP.get(suffix, 'unknown')

    def should_skip_file(self, filepath: Path) -> bool:
        """判断是否应该跳过该文件"""
        # 跳过隐藏文件和目录
        if any(part.startswith('.') for part in filepath.parts):
            return True

        # 跳过常见的生成文件和目录
        skip_patterns = [
            'node_modules', '__pycache__', 'venv', 'env',
            'dist', 'build', '.git', '.idea', '.vscode'
        ]
        if any(pattern in str(filepath) for pattern in skip_patterns):
            return True

        # 如果指定了文件扩展名，只处理匹配的文件
        if self.file_ext and filepath.suffix != self.file_ext:
            return True

        # 只处理支持的文件类型
        if filepath.suffix.lower() not in self.LANGUAGE_MAP:
            return True

        return False

    def analyze_file(self, filepath: Path) -> Dict[str, Any]:
        """分析单个文件"""
        file_result = {
            'path': str(filepath.relative_to(self.input_dir)),
            'language': self.detect_language(filepath),
            'size_bytes': filepath.stat().st_size,
            'lines': 0,
            'comment_lines': 0,
            'issues': [],
            'content_lines': [],  # 保存代码行内容，用于报告生成
            'huawei_score': None  # 华为规范评分（仅Java文件）
        }

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.split('\n')
                file_result['lines'] = len(lines)
                file_result['content_lines'] = lines

            # 根据语言选择分析方法
            language = file_result['language']

            # 先进行通用问题检查（更可靠）
            issues = self.check_generic_issues(content, filepath, language)

            # 再进行语言特定分析
            if language == 'python':
                issues.extend(self.analyze_python(content, filepath))
            elif language in ['javascript', 'typescript']:
                issues.extend(self.analyze_javascript(content, filepath))
            elif language == 'java':
                issues.extend(self.analyze_java(content, filepath))
                # 华为Java编程规范评分
                huawei_reviewer = HuaweiJavaReviewer()
                file_result['huawei_score'] = huawei_reviewer.review(content, filepath)

            file_result['issues'] = issues
            file_result['comment_lines'] = self.count_comments(content, language)

            self.results['statistics']['total_lines'] += file_result['lines']
            self.results['statistics']['comment_lines'] += file_result['comment_lines']

        except Exception as e:
            file_result['error'] = str(e)

        return file_result

    def count_comments(self, content: str, language: str) -> int:
        """统计注释行数"""
        lines = content.split('\n')
        comment_count = 0

        # 单行注释模式
        if language == 'python':
            pattern = r'^\s*#'
        elif language in ['javascript', 'typescript', 'java', 'c', 'cpp']:
            pattern = r'^\s*//'
        else:
            pattern = r'^\s*(#|//)'

        for line in lines:
            if re.match(pattern, line.strip()) or line.strip().startswith('/*'):
                comment_count += 1

        return comment_count

    def analyze_python(self, content: str, filepath: Path) -> List[Dict[str, Any]]:
        """分析Python代码"""
        issues = []

        try:
            # 使用AST进行更精确的分析
            tree = ast.parse(content)

            # 检查函数定义
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # 检查函数长度
                    if hasattr(node, 'end_lineno') and node.lineno:
                        func_length = node.end_lineno - node.lineno
                        if func_length > 50:
                            issues.append({
                                'type': '代码可读性',
                                'line': node.lineno,
                                'severity': self.SEVERITY_OPTIMIZE,
                                'description': f'函数 {node.name} 过长（{func_length}行）',
                                'suggestion': '建议将函数拆分为更小的子函数'
                            })

        except SyntaxError:
            # 如果AST解析失败，使用正则表达式作为后备
            pass

        return issues

    def analyze_javascript(self, content: str, filepath: Path) -> List[Dict[str, Any]]:
        """分析JavaScript/TypeScript代码"""
        issues = []

        # 检查常见的JavaScript问题
        # 检查var使用（建议使用let/const）
        var_pattern = r'\bvar\s+([a-zA-Z_$][a-zA-Z0-9_$]*)'
        for match in re.finditer(var_pattern, content):
            issues.append({
                'type': '代码规范性',
                'line': content[:match.start()].count('\n') + 1,
                'severity': self.SEVERITY_OPTIMIZE,
                'description': f'使用var声明变量 {match.group(1)}',
                'suggestion': '建议使用let或const代替var'
            })

        # 检查console.log
        console_pattern = r'console\.(log|warn|error|debug)\s*\('
        for match in re.finditer(console_pattern, content):
            issues.append({
                'type': '潜在Bug',
                'line': content[:match.start()].count('\n') + 1,
                'severity': self.SEVERITY_NORMAL,
                'description': '存在调试代码',
                'suggestion': '生产代码中应移除console调用'
            })

        return issues

    def analyze_java(self, content: str, filepath: Path) -> List[Dict[str, Any]]:
        """分析Java代码"""
        issues = []
        # Java特定检查可以在此添加
        return issues

    def analyze_generic(self, content: str, filepath: Path) -> List[Dict[str, Any]]:
        """通用代码分析（适用于所有语言）"""
        issues = []
        # 已被 check_generic_issues 替代
        return issues

    def check_generic_issues(self, content: str, filepath: Path, language: str) -> List[Dict[str, Any]]:
        """通用问题检查"""
        issues = []
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # 检查行长度
            if len(line) > 120:
                issues.append({
                    'type': '代码可读性',
                    'line': i,
                    'severity': self.SEVERITY_OPTIMIZE,
                    'description': f'代码行过长（{len(line)}字符）',
                    'suggestion': '建议将长行拆分为多行，推荐不超过80字符'
                })

            # 检查TODO注释
            if 'TODO' in line or 'FIXME' in line:
                issues.append({
                    'type': '代码维护性',
                    'line': i,
                    'severity': self.SEVERITY_NORMAL,
                    'description': '存在未完成的TODO标记',
                    'suggestion': '及时处理TODO项或添加工单跟踪'
                })

            # 检查空的if/try块
            stripped = line.strip()
            if stripped.endswith(':') or stripped.endswith('{'):
                # 简单启发式检查
                pass

            # 检查SQL字符串拼接（潜在的性能和安全问题）
            if re.search(r'(SELECT|INSERT|UPDATE|DELETE).*\+.*["\']', line, re.IGNORECASE):
                issues.append({
                    'type': '性能和安全',
                    'line': i,
                    'severity': self.SEVERITY_CRITICAL,
                    'description': '使用字符串拼接构建SQL查询',
                    'suggestion': '使用参数化查询或ORM框架，避免SQL注入'
                })

            # 检查硬编码的密码或密钥
            password_pattern = r'(password|passwd|pwd|secret|key|api_key)\s*=\s*["\'][^"\']{8,}'
            if re.search(password_pattern, line, re.IGNORECASE):
                issues.append({
                    'type': '安全性',
                    'line': i,
                    'severity': self.SEVERITY_CRITICAL,
                    'description': '检测到硬编码的敏感信息',
                    'suggestion': '使用环境变量或配置文件存储敏感信息'
                })

            # 检查嵌套循环（性能问题）
            if 'for' in line.lower() and lines.count('for') > 0:
                # 简化的嵌套循环检测
                pass

            # 检查空指针风险
            if language == 'python':
                if re.search(r'if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:', line):
                    var_name = re.search(r'if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:', line).group(1)
                    if var_name not in ['True', 'False', 'None']:
                        issues.append({
                            'type': '潜在Bug',
                            'line': i,
                            'severity': self.SEVERITY_NORMAL,
                            'description': f'可能存在空指针风险：{var_name}',
                            'suggestion': '显式检查变量是否为None'
                        })

        # 检查文件命名规范
        self.check_file_naming(filepath, issues)

        return issues

    def check_file_naming(self, filepath: Path, issues: List[Dict[str, Any]]):
        """检查文件命名规范"""
        filename = filepath.name
        language = self.detect_language(filepath)

        if language == 'python':
            # Python文件应使用小写加下划线
            if not re.match(r'^[a-z][a-z0-9_]*\.py$', filename):
                issues.append({
                    'type': '命名规范',
                    'line': 0,
                    'severity': self.SEVERITY_NORMAL,
                    'description': f'Python文件名不符合snake_case规范: {filename}',
                    'suggestion': '使用小写字母和下划线，如 my_module.py'
                })
        elif language in ['javascript', 'typescript']:
            # JS/TS文件应使用kebab-case或camelCase
            if not re.match(r'^[a-z][a-z0-9_-]*(\.(js|jsx|ts|tsx))$', filename):
                issues.append({
                    'type': '命名规范',
                    'line': 0,
                    'severity': self.SEVERITY_OPTIMIZE,
                    'description': f'文件命名不符合常见规范: {filename}',
                    'suggestion': '建议使用kebab-case (my-component.js) 或 camelCase (myComponent.js)'
                })

    def run(self):
        """运行审查"""
        if not self.input_dir.exists():
            raise FileNotFoundError(f'目录不存在: {self.input_dir}')

        java_files_count = 0
        total_huawei_score = 0

        # 遍历所有文件
        for root, dirs, files in os.walk(self.input_dir):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                filepath = Path(root) / filename

                if self.should_skip_file(filepath):
                    continue

                self.results['total_files'] += 1
                file_result = self.analyze_file(filepath)
                self.results['file_details'][file_result['path']] = file_result
                self.results['files_analyzed'] += 1

                # 收集问题
                for issue in file_result.get('issues', []):
                    issue['file'] = file_result['path']
                    if issue['severity'] == self.SEVERITY_CRITICAL:
                        self.results['issues']['critical'].append(issue)
                    elif issue['severity'] == self.SEVERITY_NORMAL:
                        self.results['issues']['normal'].append(issue)
                    else:
                        self.results['issues']['optimize'].append(issue)

                # 统计华为规范评分
                if file_result.get('huawei_score'):
                    java_files_count += 1
                    total_huawei_score += file_result['huawei_score']['total_score']

        # 计算注释覆盖率
        if self.results['statistics']['total_lines'] > 0:
            self.results['statistics']['comment_coverage'] = round(
                self.results['statistics']['comment_lines'] / self.results['statistics']['total_lines'] * 100,
                2
            )

        # 计算华为规范平均评分
        if java_files_count > 0:
            avg_score = total_huawei_score / java_files_count
            self.results['huawei_score'] = {
                'average_score': round(avg_score, 2),
                'java_files_count': java_files_count,
                'grade': self._get_grade(avg_score)
            }

    def _get_grade(self, score: float) -> str:
        """根据分数返回评级"""
        if score >= 90:
            return '优秀'
        elif score >= 80:
            return '良好'
        elif score >= 70:
            return '合格'
        elif score >= 60:
            return '需改进'
        else:
            return '不合格'

    def save_results(self, output_path: str = './review_results.json'):
        """保存审查结果"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='代码审查工具')
    parser.add_argument('--input-dir', required=True, help='要审查的文件夹路径')
    parser.add_argument('--file-ext', help='只处理特定扩展名的文件（如 .py）')
    parser.add_argument('--output', default='./review_results.json', help='结果输出文件路径')

    args = parser.parse_args()

    reviewer = CodeReviewer(args.input_dir, args.file_ext)
    print(f'开始审查目录: {args.input_dir}')
    reviewer.run()

    print(f'审查完成！')
    print(f'  - 扫描文件: {reviewer.results["total_files"]}')
    print(f'  - 分析文件: {reviewer.results["files_analyzed"]}')
    print(f'  - 严重问题: {len(reviewer.results["issues"]["critical"])}')
    print(f'  - 一般问题: {len(reviewer.results["issues"]["normal"])}')
    print(f'  - 优化建议: {len(reviewer.results["issues"]["optimize"])}')
    print(f'  - 注释覆盖率: {reviewer.results["statistics"]["comment_coverage"]}%')

    if reviewer.results.get('huawei_score'):
        print(f'  - 华为规范评分: {reviewer.results["huawei_score"]["average_score"]}/100 ({reviewer.results["huawei_score"]["grade"]})')

    reviewer.save_results(args.output)
    print(f'结果已保存到: {args.output}')


if __name__ == '__main__':
    main()
