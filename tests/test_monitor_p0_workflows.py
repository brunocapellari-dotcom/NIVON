import unittest
from datetime import datetime, timedelta, timezone
from nivon.monitor_p0_workflows import assess,expected_slots,render_markdown

UTC=timezone.utc
NOW=datetime(2026,10,23,19,0,tzinfo=UTC) # sexta, 15h MT
def run(id,time,result,event="push",status="completed"):
    return {"id":id,"created_at":time.isoformat(),"conclusion":result,
            "event":event,"status":status}

class TestMonitorP0(unittest.TestCase):
    def test_fail_after_success_not_masked(self):
        data=[run(1,NOW-timedelta(hours=2),"failure"),
              run(2,NOW-timedelta(hours=3),"success")]
        self.assertEqual(assess("CEPEA",data,now=NOW)["status"],"EXECUTION_FAILURE")
    def test_latest_success_not_same_as_schedule(self):
        result=assess("IMEA",[run(1,NOW-timedelta(hours=1),"success")],now=NOW)
        self.assertEqual(result["status"],"SCHEDULE_NOT_OBSERVED")
        self.assertIsNone(result["last_scheduled_execution_at"])
        self.assertFalse(result["data_freshness_evaluated"])
    def test_schedule_success_after_recent_slot(self):
        at=datetime(2026,10,23,14,10,tzinfo=UTC)
        report=assess("IMEA",[run(1,at,"success","schedule")],
                      now=datetime(2026,10,23,15,40,tzinfo=UTC))
        self.assertEqual(report["status"],"RUN_OK_NO_DATA_FRESHNESS_ASSERTION")
    def test_scheduled_failure_counts(self):
        report=assess("IMEA",[run(1,datetime(2026,10,23,14,12,tzinfo=UTC),"failure","schedule")],
                      now=datetime(2026,10,23,15,42,tzinfo=UTC))
        self.assertEqual(report["status"],"EXECUTION_FAILURE")
    def test_last_schedule_old_but_manual_success_doesnt_hide_cron(self):
        x=[run(1,NOW-timedelta(minutes=15),"success"),
           run(2,datetime(2026,10,22,14,0,tzinfo=UTC),"success","schedule")]
        self.assertEqual(assess("IMEA",x,now=NOW)["status"],"SCHEDULE_LAG")
    def test_weekend_slots_skipped(self):
        start=datetime(2026,10,24,0,0,tzinfo=UTC)
        end=datetime(2026,10,26,13,0,tzinfo=UTC)
        self.assertEqual(expected_slots(start,end,"CONAB"),[])
    def test_cepea_two_distinct_slots(self):
        begin=datetime(2026,10,23,22,0,tzinfo=UTC)
        end=datetime(2026,10,24,1,0,tzinfo=UTC)
        slots=expected_slots(begin,end,"CEPEA")
        self.assertEqual([x.hour*60+x.minute for x in slots],[23*60,23*60+45])
    def test_no_runs(self):
        self.assertEqual(assess("CONAB",[],now=NOW)["status"],"NO_EXECUTIONS")
    def test_summary_does_not_claim_current_prices(self):
        row=assess("CEPEA",[run(1,NOW,"success")],now=NOW)
        text=render_markdown([row])
        self.assertIn("não garante a atualização",text)
        self.assertIn("Neon",text)

if __name__=="__main__":unittest.main()
