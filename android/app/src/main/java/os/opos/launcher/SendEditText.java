package os.opos.launcher;

import android.content.Context;
import android.util.AttributeSet;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.widget.EditText;

/** Keeps a growing prompt while advertising the Send action to soft keyboards. */
public final class SendEditText extends EditText {
    public SendEditText(Context context, AttributeSet attributes) {
        super(context, attributes);
    }

    @Override
    public InputConnection onCreateInputConnection(EditorInfo attributes) {
        InputConnection connection = super.onCreateInputConnection(attributes);
        if (connection != null) {
            attributes.imeOptions &= ~EditorInfo.IME_FLAG_NO_ENTER_ACTION;
            attributes.imeOptions = (attributes.imeOptions & ~EditorInfo.IME_MASK_ACTION)
                    | EditorInfo.IME_ACTION_SEND;
        }
        return connection;
    }
}
