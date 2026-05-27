import copy
import json
import logging
import os

import dotenv
import requests

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def read_lines(filename):
    with open(filename, "r") as file:
        return file.read().splitlines()


def write_lines(filename, lines):
    with open(filename, "w") as file:
        file.write("\n".join(lines))


def read_json(filename):
    with open(filename, "r") as file:
        return json.load(file)


def write_json(filename, data):
    with open(filename, "w") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


class Vjudge:
    DEFAULT_DATA = {
        "method": "2",
        "language": "",  # 归档模式下为空
        "open": "1",  # 是否公开代码
        "source": "",  # 归档模式下为空
        "oj": None,  # OJ 平台
        "probNum": None,  # 题目编号
    }

    SUBMIT_URL = "https://vjudge.net/problem/submit"

    HEADERS = {
        "x-requested-with": "XMLHttpRequest",
        "referer": "https://vjudge.net/",
    }

    def __init__(self):
        if not dotenv.find_dotenv():
            logging.error("❗ 未找到 .env 文件")
            return

        dotenv.load_dotenv()
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._load_cookies()
        self.oj_config = {
            "atcoder": {"oj": "AtCoder"},
            "codeforces": {"oj": "CodeForces"},
            "luogu": {"oj": "洛谷"},
        }

        self.update_problems()

    def _load_cookies(self):
        for item in os.getenv("VJUDGE_COOKIE").split("; "):
            key, value = item.split("=", 1)
            self.session.cookies.set(key, value, domain="vjudge.net")

    def reload_cookies(self):
        logging.info("🔄 重新加载 Cookie")
        dotenv.load_dotenv(override=True)
        self.session.cookies.clear()
        self._load_cookies()

    def update_problems(self):
        logging.info("开始更新做题信息")

        self.fetch("atcoder")
        self.fetch("codeforces")
        self.fetch("luogu")

    def fetch(self, oj_name):
        if not os.path.exists(oj_name):
            os.mkdir(oj_name)
        os.chdir(oj_name)

        try:
            if oj_name == "atcoder":
                self.get_ATC_problem()
            elif oj_name == "codeforces":
                self.get_CF_problem()
            elif oj_name == "luogu":
                self.get_LG_problem()

            logging.info(f"开始提交 {oj_name} 做题信息")

            problems = read_lines("problems.txt")
            try:
                succ = read_json("success_problems.json")
            except FileNotFoundError:
                succ = {}

            def _get_i18n_key(result):
                error = result.get("error")
                if isinstance(error, dict):
                    return error.get("i18nKey", "")
                return ""

            for problem in problems:
                if (
                    problem in succ
                    and "success" in succ[problem]
                    and succ[problem]["success"]
                ):
                    continue

                i18n_key = _get_i18n_key(succ.get(problem, {}))

                if i18n_key.endswith("no_recent_submissions_found"):
                    continue

                data = copy.deepcopy(self.DEFAULT_DATA)
                for key, value in self.oj_config[oj_name].items():
                    data[key] = value
                data["probNum"] = problem

                if oj_name == "codeforces" and len(problem) > 6:
                    data["oj"] = "Gym"

                response = self.session.post(
                    f"{self.SUBMIT_URL}/{data['oj']}-{data['probNum']}",
                    data=data,
                )

                if response.status_code != 200:
                    logging.error(
                        f"❗ 发送 {data['oj']}-{data['probNum']} 的更新请求失败, 状态码：{response.status_code}"
                    )
                    if response.status_code == 401:
                        logging.error(
                            "❗ 请检查 VJUDGE_COOKIE 是否已过期或从网络请求中获取完整的 Cookie（参考 README.md）"
                        )
                    continue

                result = json.loads(response.text)

                # 检测登录失效，重新加载 Cookie 并重试一次
                if _get_i18n_key(result).endswith("login_required"):
                    logging.warning(
                        f"⚠️ 更新 {data['oj']}-{data['probNum']} 时 Cookie 已失效，尝试重新加载"
                    )
                    self.reload_cookies()
                    response = self.session.post(
                        f"{self.SUBMIT_URL}/{data['oj']}-{data['probNum']}",
                        data=data,
                    )
                    if response.status_code == 200:
                        result = json.loads(response.text)
                    else:
                        logging.error(
                            f"❗ 重试 {data['oj']}-{data['probNum']} 失败，状态码：{response.status_code}"
                        )
                        continue

                    # 重试后仍然登录失败，终止当前 OJ 的提交
                    if _get_i18n_key(result).endswith("login_required"):
                        logging.error(
                            "❗ 重试后仍然登录失败，请手动更新 VJUDGE_COOKIE（参考 README.md）"
                        )
                        break

                succ[problem] = result
                write_json("success_problems.json", succ)

                i18n_key = _get_i18n_key(result)
                if result.get("success") or i18n_key.endswith(
                    "no_recent_submissions_found"
                ):
                    logging.info(f"✅ 更新 {data['oj']}-{data['probNum']} 成功")
                else:
                    i18n_map = {
                        "no_recent_submissions_found": "没有找到最近提交",
                        "login_required": "Cookie 已失效，请更新 VJUDGE_COOKIE",
                        "invalid": "远程 OJ 账号无效或未绑定",
                    }
                    error_msg = (
                        i18n_key.split(".")[-1] if i18n_key else result.get("error")
                    )
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("i18nKey", str(error_msg))
                    error_msg = i18n_map.get(error_msg, str(error_msg))
                    logging.warning(
                        f"❌ 更新 {data['oj']}-{data['probNum']} 失败，错误信息：{error_msg}"
                    )
                    # 账号无效时终止当前 OJ 的提交（后续题目也会失败）
                    if i18n_key.endswith("own_account.error.invalid"):
                        break
        finally:
            os.chdir("..")

    def get_ATC_problem(self):
        logging.info(f"获取 {'AtCoder':^10} 题目信息")
        url = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"

        try:
            submissions = read_json("submissions.json")
        except FileNotFoundError:
            submissions = []

        while True:
            try:
                last_time = submissions[-1]["epoch_second"] + 1
            except IndexError:
                last_time = 0
            params = {"user": os.getenv("ATC_USER"), "from_second": last_time}

            # 获取最新提交记录
            response = requests.get(url, params=params).json()
            submissions.extend(response)

            if response == []:
                break

        write_json("submissions.json", submissions)

        # 得到所有题目编号
        try:
            problems = set(read_lines("problems.txt"))
        except FileNotFoundError:
            problems = set()

        for item in submissions:
            problems.add(item["problem_id"])

        write_lines("problems.txt", list(problems))
        logging.info(f"获取 {'AtCoder':^10} 题目信息成功, 共 {len(problems)} 道题目")

    def get_CF_problem(self):
        logging.info(f"获取 {'Codeforces':^10} 题目信息")
        url = "https://codeforces.com/api/user.status"
        params = {"handle": os.getenv("CF_USER")}

        response = requests.get(url, params=params).json()

        write_json("submissions.json", response)

        try:
            problems = set(read_lines("problems.txt"))
        except FileNotFoundError:
            problems = set()

        submissions = response["result"]

        for item in submissions:
            problems.add(str(item["problem"]["contestId"]) + item["problem"]["index"])

        write_lines("problems.txt", list(problems))
        logging.info(f"获取 {'Codeforces':^10} 题目信息成功, 共 {len(problems)} 道题目")

    def get_LG_problem(self):
        logging.info(f"获取 {'Luogu':^10} 题目信息")

        try:
            problems = read_lines("problems.txt")
        except FileNotFoundError:
            problems = []

        for item in [
            "暂无评定",
            "入门",
            "普及−",
            "普及/提高−",
            "普及+/提高",
            "提高+/省选−",
            "省选/NOI−",
            "NOI/NOI+/CTSC",
        ]:
            if item in problems:
                problems.remove(item)  # 删除无效信息

        write_lines("problems.txt", problems)
        logging.info(f"获取 {'Luogu':^10} 题目信息成功, 共 {len(problems)} 道题目")


if __name__ == "__main__":
    vju = Vjudge()
