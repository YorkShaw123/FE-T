#!/usr/bin/env python3
"""
代码审查报告生成器
将审查结果JSON转换为Markdown格式报告
支持华为Java编程规范评分展示
"""

import json
import argparse
from pathlib import Path
from datetime import datetime


class ReportGenerator:
    """报告生成器"""

    SEVERITY_ORDER = ['严重', '一般', '优化']
    SEVERITY_EMOJI = {
        '严重': '🔴',
        '一般': '🟡',
        '优化': '🔵'
    }
    SEVERITY_KEY_MAP = {
        '严重': 'critical',
        '一般': 'normal',
        '优化': 'optimize'
    }

    def __init__(self, review_json_path: str, output_dir: str = '.'):
        self.review_json_path = Path(review_json_path)
        self.output_dir = Path(output_dir)
        self.data = None

    def load_review_data(self):
        """加载审查数据"""
        if not self.review_json_path.exists():
            raise FileNotFoundError(f'审查结果文件不存在: {self.review_json_path}')

        with open(self.review_json_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

    def generate_markdown(self) -> str:
        """生成Markdown报告"""
        if not self.data:
            raise ValueError('未加载审查数据')

        lines = []

        # 标题和概览
        lines.extend(self._generate_header())
        lines.append('')

        # 统计信息
        lines.extend(self._generate_statistics())
        lines.append('')

        # 华为规范评分（如果有）
        if self.data.get('huawei_score'):
            lines.extend(self._generate_huawei_score_section())
            lines.append('')

        # 按严重性分类的问题
        for severity in self.SEVERITY_ORDER:
            issue_key = self.SEVERITY_KEY_MAP.get(severity, severity.lower())
            issues = self.data['issues'].get(issue_key, [])
            if issues:
                lines.extend(self._generate_issues_section(severity, issues))
                lines.append('')

        # 文件级别详细分析
        lines.extend(self._generate_file_details())
        lines.append('')

        # 可读性评估
        lines.extend(self._generate_readability_section())
        lines.append('')

        # 附录和说明
        lines.extend(self._generate_appendix())

        return '\n'.join(lines)

    def _get_code_line(self, file_path: str, line_number: int) -> str:
        """获取指定文件的指定行代码"""
        if not line_number or line_number <= 0:
            return ''

        # 从 file_details 中获取代码行
        file_details = self.data.get('file_details', {}).get(file_path, {})
        content_lines = file_details.get('content_lines', [])

        if 0 < line_number <= len(content_lines):
            return content_lines[line_number - 1]

        return ''

    def _generate_header(self) -> list:
        """生成报告头部"""
        timestamp = datetime.fromisoformat(self.data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')

        return [
            '# 代码审查报告',
            '',
            f'**审查时间**: {timestamp}',
            f'**审查目录**: `{self.data["input_dir"]}`',
            f'**扫描文件**: {self.data["files_analyzed"]} / {self.data["total_files"]}',
            ''
        ]

    def _generate_statistics(self) -> list:
        """生成统计信息"""
        total_issues = sum(len(issues) for issues in self.data['issues'].values())
        critical = len(self.data['issues']['critical'])
        normal = len(self.data['issues']['normal'])
        optimize = len(self.data['issues']['optimize'])

        return [
            '## 📊 审查统计',
            '',
            f'- **总问题数**: {total_issues}',
            f'- **严重问题**: {critical} {self.SEVERITY_EMOJI["严重"]}',
            f'- **一般问题**: {normal} {self.SEVERITY_EMOJI["一般"]}',
            f'- **优化建议**: {optimize} {self.SEVERITY_EMOJI["优化"]}',
            '',
            '### 代码指标',
            '',
            f'- **总代码行数**: {self.data["statistics"]["total_lines"]}',
            f'- **注释行数**: {self.data["statistics"]["comment_lines"]}',
            f'- **注释覆盖率**: {self.data["statistics"]["comment_coverage"]}%',
            ''
        ]

    def _generate_huawei_score_section(self) -> list:
        """生成华为规范评分章节"""
        huawei_score = self.data.get('huawei_score', {})
        if not huawei_score:
            return []

        lines = [
            '## 🏆 华为Java编程规范评分',
            '',
            f'**平均得分**: {huawei_score["average_score"]}/100',
            f'**评级**: {self._get_score_emoji(huawei_score["average_score"])} {huawei_score["grade"]}',
            f'**Java文件数**: {huawei_score["java_files_count"]}',
            ''
        ]

        # 收集所有文件的评分详情
        all_categories = {
            'layout': {'name': '排版规范', 'total_deductions': 0, 'all_suggestions': set()},
            'comment': {'name': '注释规范', 'total_deductions': 0, 'all_suggestions': set()},
            'naming': {'name': '命名规范', 'total_deductions': 0, 'all_suggestions': set()},
            'coding': {'name': '代码编写规范', 'total_deductions': 0, 'all_suggestions': set()},
            'performance': {'name': '性能与可靠性', 'total_deductions': 0, 'all_suggestions': set()}
        }

        # 遍历所有文件，收集评分详情
        for file_path, details in self.data.get('file_details', {}).items():
            file_score = details.get('huawei_score')
            if not file_score:
                continue

            for cat_key, cat_data in file_score.get('categories', {}).items():
                if cat_key in all_categories:
                    # 计算扣分
                    for deduction in cat_data.get('deductions', []):
                        all_categories[cat_key]['total_deductions'] += deduction.get('deduction', 0)

                    # 收集建议
                    for suggestion in cat_data.get('suggestions', []):
                        all_categories[cat_key]['all_suggestions'].add(suggestion)

        # 生成各类别评分详情
        lines.append('### 各类别评分详情')
        lines.append('')
        lines.append('| 类别 | 满分 | 扣分 | 得分 |')
        lines.append('|------|------|------|------|')

        category_scores = {
            'layout': 20,
            'comment': 25,
            'naming': 20,
            'coding': 20,
            'performance': 15
        }

        for cat_key, cat_info in all_categories.items():
            max_score = category_scores[cat_key]
            deduction = cat_info['total_deductions']
            score = max_score - deduction
            lines.append(f'| {cat_info["name"]} | {max_score} | -{deduction} | {score} |')

        lines.append('')

        # 生成修改建议
        lines.append('### 📝 修改建议')
        lines.append('')

        for cat_key, cat_info in all_categories.items():
            if cat_info['all_suggestions']:
                lines.append(f'#### {cat_info["name"]}')
                lines.append('')
                for i, suggestion in enumerate(list(cat_info['all_suggestions'])[:5], 1):
                    lines.append(f'{i}. {suggestion}')
                lines.append('')

        # 生成各文件详细评分
        lines.append('### 📄 各文件详细评分')
        lines.append('')
        lines.append('| 文件 | 得分 | 评级 |')
        lines.append('|------|------|------|')

        for file_path, details in self.data.get('file_details', {}).items():
            file_score = details.get('huawei_score')
            if file_score:
                score = file_score['total_score']
                grade = file_score['grade']
                emoji = self._get_score_emoji(score)
                lines.append(f'| {file_path} | {score}/100 | {emoji} {grade} |')

        lines.append('')

        return lines

    def _get_score_emoji(self, score: float) -> str:
        """根据分数返回对应的emoji"""
        if score >= 90:
            return '🟢'
        elif score >= 80:
            return '🟡'
        elif score >= 70:
            return '🟠'
        else:
            return '🔴'

    def _generate_issues_section(self, severity: str, issues: list) -> list:
        """生成问题列表章节"""
        emoji = self.SEVERITY_EMOJI[severity]
        lines = [
            f'## {emoji} {severity}问题 ({len(issues)})',
            '',
            '| 文件 | 类型 | 行号 | 描述 | 建议 |',
            '|------|------|------|------|------|'
        ]

        # 按类型分组统计
        type_count = {}
        for issue in issues:
            issue_type = issue.get('type', '未知')
            type_count[issue_type] = type_count.get(issue_type, 0) + 1

        lines.append('')
        lines.append('### 问题分布')
        for issue_type, count in type_count.items():
            lines.append(f'- **{issue_type}**: {count}')
        lines.append('')

        # 详细问题列表
        lines.append('### 详细列表')
        for issue in issues[:50]:  # 限制显示数量
            file_path = issue.get('file', '未知')
            issue_type = issue.get('type', '未知')
            line = issue.get('line', '-')
            description = issue.get('description', '无描述')
            suggestion = issue.get('suggestion', '无建议')

            # 转义表格中的特殊字符
            description = description.replace('|', '\\|').replace('\n', ' ')
            suggestion = suggestion.replace('|', '\\|').replace('\n', ' ')

            lines.append(f'| {file_path} | {issue_type} | {line} | {description} | {suggestion} |')

        # 对于严重问题，添加代码行展示
        if severity == '严重' and issues:
            lines.append('')
            lines.append('### 🔍 严重问题代码详情')
            lines.append('')

            for issue in issues[:20]:  # 限制显示前20个严重问题
                file_path = issue.get('file', '未知')
                line_number = issue.get('line', 0)

                # 获取代码行内容
                code_line = self._get_code_line(file_path, line_number)

                if code_line:
                    lines.append(f'#### {file_path}:{line_number}')
                    lines.append('')
                    lines.append('```')
                    lines.append(code_line.rstrip())
                    lines.append('```')
                    lines.append('')
                    lines.append(f'**问题**: {issue.get("description", "无描述")}')
                    lines.append(f'**建议**: {issue.get("suggestion", "无建议")}')
                    lines.append('')

        if len(issues) > 50:
            lines.append(f'\n*... 还有 {len(issues) - 50} 个问题未显示，请查看详细JSON文件*')

        return lines

    def _generate_file_details(self) -> list:
        """生成文件级别详细分析"""
        lines = [
            '## 📁 文件级别分析',
            '',
            '| 文件 | 语言 | 行数 | 问题数 | 注释行 |',
            '|------|------|------|--------|--------|'
        ]

        for file_path, details in self.data['file_details'].items():
            language = details.get('language', '未知')
            lines_count = details.get('lines', 0)
            issues_count = len(details.get('issues', []))
            comment_lines = details.get('comment_lines', 0)

            lines.append(f'| {file_path} | {language} | {lines_count} | {issues_count} | {comment_lines} |')

        return lines

    def _generate_readability_section(self) -> list:
        """生成可读性评估章节"""
        comment_coverage = self.data['statistics']['comment_coverage']

        # 评估可读性
        if comment_coverage >= 20:
            readability_level = '优秀'
            readability_color = '🟢'
        elif comment_coverage >= 10:
            readability_level = '良好'
            readability_color = '🟡'
        else:
            readability_level = '需改进'
            readability_color = '🔴'

        lines = [
            '## 📖 代码可读性评估',
            '',
            f'**整体评级**: {readability_color} {readability_level}',
            '',
            '### 评估指标',
            '',
            f'1. **注释覆盖率**: {comment_coverage}%'
        ]

        if comment_coverage >= 20:
            lines.append('   - 评价: 代码注释充分，易于理解')
        elif comment_coverage >= 10:
            lines.append('   - 评价: 注释基本覆盖关键逻辑，建议补充复杂算法的说明')
        else:
            lines.append('   - 评价: 注释覆盖率偏低，建议增加函数和复杂逻辑的注释')

        lines.append('')
        lines.append('### 改进建议')
        lines.append('')
        lines.append('1. **函数和类**: 为每个公共函数和类添加文档字符串')
        lines.append('2. **复杂逻辑**: 为复杂的算法和业务逻辑添加详细注释')
        lines.append('3. **常量说明**: 为魔法数字和常量添加说明')
        lines.append('4. **代码格式**: 保持一致的代码格式和缩进风格')

        return lines

    def _generate_appendix(self) -> list:
        """生成附录"""
        return [
            '## 📝 附录',
            '',
            '### 严重性定义',
            '',
            '- **严重** 🔴: 可能导致功能错误、安全漏洞或系统崩溃的问题，必须立即修复',
            '- **一般** 🟡: 影响代码质量、可维护性或可读性的问题，建议在下次迭代中修复',
            '- **优化** 🔵: 性能优化、代码风格或最佳实践建议，可根据项目进度安排',
            '',
            '### 检查类型说明',
            '',
            '- **代码规范性**: 文件命名、变量命名、代码格式等规范问题',
            '- **潜在Bug**: 可能导致运行时错误的代码模式',
            '- **性能和安全**: 性能问题和安全漏洞风险',
            '- **代码可读性**: 代码长度、复杂度等可读性问题',
            '- **代码维护性**: TODO、FIXME等未完成项',
            '- **命名规范**: 不符合语言命名规范的标识符',
            '- **安全性**: 硬编码密钥、SQL注入风险等安全问题',
            '',
            '### 华为Java编程规范评分说明',
            '',
            '评分基于《华为Java编程规范》，总分100分，分为5个维度：',
            '',
            '- **排版规范**（20分）：缩进、分界符、行长度、语句格式等',
            '- **注释规范**（25分）：注释量、类注释、方法注释、JavaDoc等',
            '- **命名规范**（20分）：类名、方法名、变量名、常量名等',
            '- **代码编写规范**（20分）：日志使用、魔法数字、泛型、异常处理等',
            '- **性能与可靠性**（15分）：日志级别判断、字符串拼接、性能优化等',
            '',
            '**评级标准**：',
            '- 🟢 优秀（90-100分）',
            '- 🟡 良好（80-89分）',
            '- 🟠 合格（70-79分）',
            '- 🔴 需改进（<70分）',
            '',
            '---',
            '',
            f'*本报告由代码审查工具自动生成 - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*'
        ]

    def save_report(self, filename: str = 'code_review_report.md'):
        """保存报告"""
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

        output_path = self.output_dir / filename
        markdown_content = self.generate_markdown()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        return output_path


def main():
    parser = argparse.ArgumentParser(description='代码审查报告生成器')
    parser.add_argument('--review-json', default='./review_results.json',
                        help='审查结果JSON文件路径')
    parser.add_argument('--output-dir', default='.',
                        help='报告输出目录')
    parser.add_argument('--output-file', default='code_review_report.md',
                        help='报告文件名')

    args = parser.parse_args()

    generator = ReportGenerator(args.review_json, args.output_dir)
    print('加载审查数据...')
    generator.load_review_data()

    print('生成Markdown报告...')
    output_path = generator.save_report(args.output_file)

    print(f'报告已生成: {output_path}')


if __name__ == '__main__':
    main()
